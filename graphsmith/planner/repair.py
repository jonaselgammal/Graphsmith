"""Deterministic local IR repair for structured control-flow blocks.

This is intentionally narrow: it only patches block-local contract gaps
that can be inferred from the surrounding IR without another LLM call.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from graphsmith.constants import PRIMITIVE_OPS
from graphsmith.planner.compiler import (
    CompilerError,
    InvalidBranchBlockError,
    InvalidLoopBlockError,
)
from graphsmith.planner.ir import IRBlock, IROutputRef, IRSource, IRStep, PlanningIR


class RepairAction(BaseModel):
    """One deterministic local repair applied to the IR."""

    target: str
    action: str
    reason: str = ""


class RepairResult(BaseModel):
    """Result of attempting deterministic local repair."""

    ir: PlanningIR
    actions: list[RepairAction] = Field(default_factory=list)


def repair_ir_locally(ir: PlanningIR, error: CompilerError) -> RepairResult:
    """Attempt a narrow local repair based on a compiler failure."""
    actions: list[RepairAction] = []
    repaired = ir

    if isinstance(error, InvalidLoopBlockError):
        repaired, actions = _repair_loop_block(repaired, error)
    elif isinstance(error, InvalidBranchBlockError):
        repaired, actions = _repair_branch_block(repaired, error)

    return RepairResult(ir=repaired, actions=actions)


def normalize_ir_contracts(ir: PlanningIR) -> RepairResult:
    """Apply deterministic step-level contract normalizations before compile."""
    actions: list[RepairAction] = []
    port_aliases: dict[str, dict[str, str]] = {}
    steps: list[IRStep] = []
    for step in ir.steps:
        normalized_step, aliases = _normalize_step_contracts(step, actions)
        steps.append(normalized_step)
        if aliases:
            port_aliases[step.name] = aliases
    blocks = [_normalize_block_contracts(block, actions) for block in ir.blocks]
    final_outputs = {
        name: _rewrite_output_alias(ref, port_aliases)
        for name, ref in ir.final_outputs.items()
    }
    return RepairResult(
        ir=ir.model_copy(update={"steps": steps, "blocks": blocks, "final_outputs": final_outputs}),
        actions=actions,
    )


def _repair_loop_block(
    ir: PlanningIR, error: InvalidLoopBlockError,
) -> tuple[PlanningIR, list[RepairAction]]:
    block_name = str(error.details.get("block_name", ""))
    actions: list[RepairAction] = []
    updated_blocks = []

    for block in ir.blocks:
        if block.name != block_name or block.kind != "loop":
            updated_blocks.append(block)
            continue

        updated = block
        if not updated.final_outputs:
            desired_ports = _infer_block_output_ports(ir, block_name)
            if desired_ports and updated.steps:
                terminal_step = updated.steps[-1].name
                updated = updated.model_copy(
                    update={
                        "final_outputs": {
                            port: IROutputRef(step=terminal_step, port=port)
                            for port in desired_ports
                        }
                    }
                )
                actions.append(
                    RepairAction(
                        target=f"loop:{block_name}",
                        action=f"infer final_outputs from parent references via terminal step '{terminal_step}'",
                        reason="loop block omitted final_outputs",
                    )
                )

        item_bound = any(source.binding == "item" for source in updated.inputs.values())
        if not item_bound and len(updated.inputs) == 1:
            input_name = next(iter(updated.inputs))
            new_inputs = dict(updated.inputs)
            new_inputs[input_name] = IRSource(binding="item")
            updated = updated.model_copy(update={"inputs": new_inputs})
            actions.append(
                RepairAction(
                    target=f"loop:{block_name}",
                    action=f"bind loop input '{input_name}' to $item",
                    reason="loop block had one body input and no explicit item binding",
                )
            )

        updated_blocks.append(updated)

    return ir.model_copy(update={"blocks": updated_blocks}), actions


def _repair_branch_block(
    ir: PlanningIR, error: InvalidBranchBlockError,
) -> tuple[PlanningIR, list[RepairAction]]:
    block_name = str(error.details.get("block_name", ""))
    actions: list[RepairAction] = []
    updated_blocks = []

    for block in ir.blocks:
        if block.name != block_name or block.kind != "branch":
            updated_blocks.append(block)
            continue

        updated = block
        desired_ports = _infer_block_output_ports(ir, block_name)

        then_outputs = dict(updated.then_outputs)
        else_outputs = dict(updated.else_outputs)

        if desired_ports:
            then_outputs, then_added = _fill_missing_branch_outputs(
                then_outputs, desired_ports, updated.then_steps,
            )
            else_outputs, else_added = _fill_missing_branch_outputs(
                else_outputs, desired_ports, updated.else_steps,
            )
            if then_added:
                actions.append(
                    RepairAction(
                        target=f"branch:{block_name}:then",
                        action=f"infer outputs {', '.join(then_added)}",
                        reason="then_outputs missing or incomplete",
                    )
                )
            if else_added:
                actions.append(
                    RepairAction(
                        target=f"branch:{block_name}:else",
                        action=f"infer outputs {', '.join(else_added)}",
                        reason="else_outputs missing or incomplete",
                    )
                )

        if then_outputs != updated.then_outputs or else_outputs != updated.else_outputs:
            updated = updated.model_copy(
                update={"then_outputs": then_outputs, "else_outputs": else_outputs}
            )

        updated_blocks.append(updated)

    return ir.model_copy(update={"blocks": updated_blocks}), actions


def _infer_block_output_ports(ir: PlanningIR, block_name: str) -> list[str]:
    ports: list[str] = []
    seen: set[str] = set()

    for ref in ir.final_outputs.values():
        if ref.step == block_name and ref.port not in seen:
            ports.append(ref.port)
            seen.add(ref.port)

    for step in ir.steps:
        for source in step.sources.values():
            if source.step == block_name and source.port and source.port not in seen:
                ports.append(source.port)
                seen.add(source.port)

    for block in ir.blocks:
        if block.name == block_name:
            continue
        if block.kind == "loop":
            refs = list(block.final_outputs.values())
        else:
            refs = [*block.then_outputs.values(), *block.else_outputs.values()]
        for ref in refs:
            if ref.step == block_name and ref.port not in seen:
                ports.append(ref.port)
                seen.add(ref.port)

    return ports


def _fill_missing_branch_outputs(
    existing: dict[str, IROutputRef],
    desired_ports: list[str],
    steps: list[object],
) -> tuple[dict[str, IROutputRef], list[str]]:
    if not steps:
        return existing, []
    repaired = dict(existing)
    terminal_step = steps[-1].name
    added: list[str] = []
    for port in desired_ports:
        if port in repaired:
            continue
        repaired[port] = IROutputRef(step=terminal_step, port=port)
        added.append(port)
    return repaired, added


def _normalize_block_contracts(
    block: IRBlock, actions: list[RepairAction],
) -> IRBlock:
    updates: dict[str, object] = {}
    if block.steps:
        updates["steps"] = [_normalize_step_contracts(step, actions)[0] for step in block.steps]
    if block.then_steps:
        updates["then_steps"] = [
            _normalize_step_contracts(step, actions)[0] for step in block.then_steps
        ]
    if block.else_steps:
        updates["else_steps"] = [
            _normalize_step_contracts(step, actions)[0] for step in block.else_steps
        ]
    if not updates:
        return block
    return block.model_copy(update=updates)


def _normalize_step_contracts(
    step: IRStep, actions: list[RepairAction],
) -> tuple[IRStep, dict[str, str]]:
    repaired = step
    port_aliases: dict[str, str] = {}

    if repaired.skill_id == "branch.if":
        sources = dict(repaired.sources)
        changed = False
        if "if_true" in sources and "then_value" not in sources:
            sources["then_value"] = sources.pop("if_true")
            changed = True
        if "if_false" in sources and "else_value" not in sources:
            sources["else_value"] = sources.pop("if_false")
            changed = True
        if changed:
            repaired = repaired.model_copy(update={"sources": sources})
            actions.append(
                RepairAction(
                    target=f"step:{step.name}",
                    action="normalize branch.if inputs to then_value/else_value",
                    reason="planner used legacy branch.if source names",
                )
            )

    if repaired.skill_id == "array.map":
        sources = dict(repaired.sources)
        config = dict(repaired.config)
        source_changed = False
        if "array" in sources and "items" not in sources:
            sources["items"] = sources.pop("array")
            source_changed = True
            actions.append(
                RepairAction(
                    target=f"step:{step.name}",
                    action="rename array.map source 'array' to 'items'",
                    reason="array.map runtime expects items input",
                )
            )
        if "operation" in config and "items" in sources:
            inner = str(config.get("operation", ""))
            if inner:
                repaired = _lift_array_map_operation(
                    repaired.model_copy(update={"sources": sources}),
                    inner,
                )
                port_aliases["mapped"] = "results"
                actions.append(
                    RepairAction(
                        target=f"step:{step.name}",
                        action=f"lift array.map operation '{inner}' to parallel.map",
                        reason="planner emitted shorthand array.map operation contract",
                    )
                )
                return repaired, port_aliases
        if source_changed:
            repaired = repaired.model_copy(update={"sources": sources, "config": config})

    return repaired, port_aliases


def _lift_array_map_operation(step: IRStep, inner: str) -> IRStep:
    if inner in PRIMITIVE_OPS:
        config: dict[str, object] = {"op": inner}
        if inner.startswith("text."):
            config["item_input"] = "text"
        elif inner.startswith("json."):
            config["item_input"] = "raw_json"
        return step.model_copy(
            update={
                "skill_id": "parallel.map",
                "sources": {"items": step.sources["items"]},
                "config": config,
            }
        )

    skill_id = inner if ".v" in inner else f"{inner}.v1"
    return step.model_copy(
        update={
            "skill_id": "parallel.map",
            "sources": {"items": step.sources["items"]},
            "config": {
                "op": "skill.invoke",
                "op_config": {
                    "skill_id": skill_id,
                    "version": "1.0.0",
                },
                "item_input": "text",
            },
        }
    )


def _rewrite_output_alias(
    ref: IROutputRef,
    port_aliases: dict[str, dict[str, str]],
) -> IROutputRef:
    aliases = port_aliases.get(ref.step, {})
    new_port = aliases.get(ref.port)
    if not new_port:
        return ref
    return IROutputRef(step=ref.step, port=new_port)
