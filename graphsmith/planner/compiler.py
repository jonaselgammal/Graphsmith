"""Deterministic IR → GlueGraph compiler.

Lowers a PlanningIR into a fully-formed GlueGraph by generating
node IDs, edges, config embedding, and graph_outputs mapping.
All decisions are deterministic — no LLM involvement.
"""
from __future__ import annotations

import re
from typing import Any

from graphsmith.constants import ALLOWED_EFFECTS, PRIMITIVE_OPS
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.planner.ir import IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.models import GlueGraph
from graphsmith.type_system import is_supported_type_spec


# ── Compiler errors ─────────────────────────────────────────────────


class CompilerError(Exception):
    """Base class for deterministic compiler errors."""

    def __init__(self, message: str, *, phase: str, details: dict[str, Any] | None = None) -> None:
        self.phase = phase
        self.details = details or {}
        super().__init__(message)


class DuplicateStepError(CompilerError):
    """Two steps share the same name."""

    def __init__(self, step_name: str) -> None:
        super().__init__(
            f"Duplicate step name: '{step_name}'",
            phase="validate_ir",
            details={"step_name": step_name},
        )


class UnknownSourceStepError(CompilerError):
    """A source references a step that doesn't exist."""

    def __init__(self, step_name: str, source_port: str, ref_step: str) -> None:
        super().__init__(
            f"Step '{step_name}' input '{source_port}' references unknown step '{ref_step}'",
            phase="validate_ir",
            details={"step_name": step_name, "source_port": source_port, "ref_step": ref_step},
        )


class UnknownOutputStepError(CompilerError):
    """A final_output references a step that doesn't exist."""

    def __init__(self, output_name: str, ref_step: str) -> None:
        super().__init__(
            f"Output '{output_name}' references unknown step '{ref_step}'",
            phase="validate_ir",
            details={"output_name": output_name, "ref_step": ref_step},
        )


class UnknownInputError(CompilerError):
    """A source references a graph input that doesn't exist."""

    def __init__(self, step_name: str, source_port: str, input_name: str) -> None:
        super().__init__(
            f"Step '{step_name}' input '{source_port}' references undeclared input '{input_name}'",
            phase="validate_ir",
            details={"step_name": step_name, "source_port": source_port, "input_name": input_name},
        )


class InvalidEffectError(CompilerError):
    """An effect is not in the allowed set."""

    def __init__(self, effect: str) -> None:
        super().__init__(
            f"Invalid effect: '{effect}'",
            phase="validate_ir",
            details={"effect": effect, "allowed": sorted(ALLOWED_EFFECTS)},
        )


class EmptyStepsError(CompilerError):
    """IR has no steps."""

    def __init__(self) -> None:
        super().__init__("IR has no steps", phase="validate_ir")


class SelfLoopError(CompilerError):
    """A step sources from itself."""

    def __init__(self, step_name: str, source_port: str) -> None:
        super().__init__(
            f"Step '{step_name}' input '{source_port}' references itself (self-loop)",
            phase="validate_ir",
            details={"step_name": step_name, "source_port": source_port},
        )


class CycleError(CompilerError):
    """The step dependency graph contains a cycle."""

    def __init__(self, involved: list[str]) -> None:
        super().__init__(
            f"Cycle detected among steps: {', '.join(involved)}",
            phase="validate_ir",
            details={"steps": involved},
        )


class DuplicateBindingError(CompilerError):
    """Two bindings share the same name."""

    def __init__(self, binding_name: str) -> None:
        super().__init__(
            f"Duplicate binding name: '{binding_name}'",
            phase="validate_ir",
            details={"binding_name": binding_name},
        )


class UnknownBindingError(CompilerError):
    """A step source references a binding that doesn't exist."""

    def __init__(self, step_name: str, source_port: str, binding_name: str) -> None:
        super().__init__(
            f"Step '{step_name}' input '{source_port}' references unknown binding '{binding_name}'",
            phase="validate_ir",
            details={"step_name": step_name, "source_port": source_port, "binding_name": binding_name},
        )


class UnsupportedControlFlowError(CompilerError):
    """The IR uses richer control-flow features that v1 cannot compile."""

    def __init__(self, block_kinds: list[str]) -> None:
        kinds = ", ".join(block_kinds)
        super().__init__(
            f"Planning IR contains unsupported control-flow blocks: {kinds}",
            phase="validate_ir",
            details={"block_kinds": block_kinds},
        )


class InvalidLoopBlockError(CompilerError):
    """A loop block is missing required semantics for lowering."""

    def __init__(self, block_name: str, message: str) -> None:
        super().__init__(
            f"Loop block '{block_name}' is invalid: {message}",
            phase="lower_blocks",
            details={"block_name": block_name},
        )


class InvalidBranchBlockError(CompilerError):
    """A branch block is missing required semantics for lowering."""

    def __init__(self, block_name: str, message: str) -> None:
        super().__init__(
            f"Branch block '{block_name}' is invalid: {message}",
            phase="lower_blocks",
            details={"block_name": block_name},
        )


# ── Step name sanitization ─────────────────────────────────────────


_SANITIZE_RE = re.compile(r"[^a-z0-9_]")


def sanitize_step_name(raw: str) -> str:
    """Normalize a raw step name into a valid graph node ID.

    - Lowercases
    - Replaces dots, hyphens, spaces, and other non-alphanumeric chars with underscores
    - Strips leading/trailing underscores
    - Collapses multiple consecutive underscores
    - Falls back to "step" if result is empty
    """
    s = raw.lower()
    s = _SANITIZE_RE.sub("_", s)
    s = re.sub(r"_+", "_", s)  # collapse runs
    s = s.strip("_")
    return s or "step"


def _build_name_map(ir: PlanningIR) -> dict[str, str]:
    """Build raw step name → sanitized name mapping, resolving collisions.

    Returns a dict mapping each original step name to its sanitized ID.
    Source references use original names, so the compiler must remap them.
    """
    name_map: dict[str, str] = {}
    used: dict[str, int] = {}  # sanitized → count for collision resolution

    for step in ir.steps:
        sanitized = sanitize_step_name(step.name)
        if sanitized in used:
            used[sanitized] += 1
            sanitized = f"{sanitized}_{used[sanitized]}"
        else:
            used[sanitized] = 1
        name_map[step.name] = sanitized

    return name_map


# ── Compiler ────────────────────────────────────────────────────────


def compile_ir(ir: PlanningIR) -> GlueGraph:
    """Compile a PlanningIR into a GlueGraph.

    Phases:
    0. Sanitize step names (deterministic normalization)
    1. Validate IR consistency (references, effects, cycles)
    2. Generate nodes from steps
    3. Generate edges from sources
    4. Build graph_outputs from final_outputs
    5. Assemble GlueGraph

    Raises CompilerError (or subclass) on any structural problem.
    """
    # Phase 0: lower supported structured blocks
    ir = _lower_supported_blocks(ir)

    # Phase 1: build sanitized name map and apply it
    name_map = _build_name_map(ir)
    ir = _apply_name_map(ir, name_map)

    _validate_richer_ir(ir)
    _validate_bindings(ir)
    ir = _expand_bindings(ir)
    _validate_ir(ir)
    nodes = _build_nodes(ir)
    edges = _build_edges(ir)
    graph_outputs = _build_graph_outputs(ir)
    inputs = [IOField(name=inp.name, type=_normalize_type(inp.type)) for inp in ir.inputs]
    outputs = _build_output_fields(ir)

    graph = GraphBody(
        version=1,
        nodes=nodes,
        edges=edges,
        outputs=graph_outputs,
    )

    return GlueGraph(
        goal=ir.goal,
        inputs=inputs,
        outputs=outputs,
        effects=ir.effects,
        graph=graph,
    )


def _apply_name_map(ir: PlanningIR, name_map: dict[str, str]) -> PlanningIR:
    """Return a new PlanningIR with all step names and references remapped."""
    if all(k == v for k, v in name_map.items()):
        return ir  # nothing to change

    new_steps: list[IRStep] = []
    for step in ir.steps:
        new_sources: dict[str, IRSource] = {}
        for port, src in step.sources.items():
            if src.binding is not None or src.step == "input":
                new_sources[port] = src
            else:
                new_sources[port] = IRSource(
                    step=name_map.get(src.step, src.step),
                    port=src.port,
                )
        new_steps.append(
            IRStep(
                name=name_map[step.name],
                skill_id=step.skill_id,
                version=step.version,
                sources=new_sources,
                config=step.config,
                when=_remap_source(step.when, name_map),
                unless=step.unless,
            )
        )

    new_bindings = []
    for binding in ir.bindings:
        if binding.source.binding is not None or binding.source.step == "input":
            source = binding.source
        else:
            source = IRSource(
                step=name_map.get(binding.source.step, binding.source.step),
                port=binding.source.port,
            )
        new_bindings.append(
            binding.model_copy(update={"source": source})
        )

    new_final_outputs: dict[str, IROutputRef] = {}
    for out_name, ref in ir.final_outputs.items():
        new_final_outputs[out_name] = IROutputRef(
            step=name_map.get(ref.step, ref.step),
            port=ref.port,
        )

    return PlanningIR(
        goal=ir.goal,
        inputs=ir.inputs,
        bindings=new_bindings,
        steps=new_steps,
        blocks=ir.blocks,
        final_outputs=new_final_outputs,
        effects=ir.effects,
        reasoning=ir.reasoning,
    )


# ── Internal phases ─────────────────────────────────────────────────


def _validate_ir(ir: PlanningIR) -> None:
    """Validate IR consistency before compilation."""
    if not ir.steps:
        raise EmptyStepsError()

    # Check for duplicate step names
    seen: set[str] = set()
    for step in ir.steps:
        if step.name in seen:
            raise DuplicateStepError(step.name)
        seen.add(step.name)

    input_names = {inp.name for inp in ir.inputs}
    step_names = {s.name for s in ir.steps}
    # Check effects
    for effect in ir.effects:
        if effect not in ALLOWED_EFFECTS:
            raise InvalidEffectError(effect)

    # Check source references
    for step in ir.steps:
        for port, source in step.sources.items():
            _validate_source_reference(
                source,
                step_name=step.name,
                source_port=port,
                input_names=input_names,
                step_names=step_names,
                binding_names=set(),
            )
        if step.when is not None:
            _validate_source_reference(
                step.when,
                step_name=step.name,
                source_port="when",
                input_names=input_names,
                step_names=step_names,
                binding_names=set(),
            )

    # Check final_output references
    for out_name, ref in ir.final_outputs.items():
        if ref.step not in step_names:
            raise UnknownOutputStepError(out_name, ref.step)

    # Check for cycles via topological sort
    _check_dag(ir)


def _validate_richer_ir(ir: PlanningIR) -> None:
    if ir.blocks:
        raise UnsupportedControlFlowError([block.kind for block in ir.blocks])


def _lower_supported_blocks(ir: PlanningIR) -> PlanningIR:
    if not ir.blocks:
        return ir

    unsupported = [block.kind for block in ir.blocks if block.kind not in {"loop", "branch"}]
    if unsupported:
        raise UnsupportedControlFlowError(unsupported)

    lowered_steps = list(ir.steps)
    block_output_map: dict[tuple[str, str], IRSource] = {}
    for block in ir.blocks:
        if block.kind == "loop":
            lowered = _lower_loop_block(block, parent_ir=ir, block_output_map=block_output_map)
        else:
            lowered = _lower_branch_block(block, parent_ir=ir, block_output_map=block_output_map)
        lowered_steps.extend(lowered["steps"])
        block_output_map.update(lowered["outputs"])

    rewritten_steps = [
        _rewrite_step_block_sources(step, block_output_map)
        for step in lowered_steps
    ]
    rewritten_outputs = {
        name: _rewrite_output_ref(ref, block_output_map)
        for name, ref in ir.final_outputs.items()
    }

    return ir.model_copy(update={"steps": rewritten_steps, "blocks": [], "final_outputs": rewritten_outputs})


def _validate_bindings(ir: PlanningIR) -> None:
    input_names = {inp.name for inp in ir.inputs}
    step_names = {s.name for s in ir.steps}
    binding_names = {b.name for b in ir.bindings}

    seen_bindings: set[str] = set()
    for binding in ir.bindings:
        if binding.name in seen_bindings:
            raise DuplicateBindingError(binding.name)
        seen_bindings.add(binding.name)
        _validate_source_reference(
            binding.source,
            step_name=f"(binding:{binding.name})",
            source_port="source",
            input_names=input_names,
            step_names=step_names,
            binding_names=set(),
        )

    for step in ir.steps:
        for port, source in step.sources.items():
            if source.binding is not None and source.binding not in binding_names:
                raise UnknownBindingError(step.name, port, source.binding)
        if step.when is not None and step.when.binding is not None and step.when.binding not in binding_names:
            raise UnknownBindingError(step.name, "when", step.when.binding)


def _lower_loop_block(
    block: Any,
    *,
    parent_ir: PlanningIR,
    block_output_map: dict[tuple[str, str], IRSource],
) -> dict[str, Any]:
    if block.collection is None:
        raise InvalidLoopBlockError(block.name, "missing collection source")
    if block.max_items < 0:
        raise InvalidLoopBlockError(block.name, "max_items must be non-negative")
    if not block.final_outputs:
        raise InvalidLoopBlockError(block.name, "must declare at least one final output")

    item_inputs: list[str] = []
    external_sources: dict[str, IRSource] = {}
    body_inputs: list[Any] = []
    for input_name, source in block.inputs.items():
        from graphsmith.planner.ir import IRInput
        body_inputs.append(IRInput(name=input_name, type="string"))
        if source.binding == "item":
            item_inputs.append(input_name)
        else:
            external_sources[input_name] = _resolve_block_source(source, block_output_map)

    if not item_inputs:
        raise InvalidLoopBlockError(
            block.name,
            "must bind at least one body input to loop item via {'binding': 'item'} or '$item'",
        )

    body_ir = PlanningIR(
        goal=f"{parent_ir.goal} :: loop {block.name}",
        inputs=body_inputs,
        steps=block.steps,
        final_outputs=block.final_outputs,
        effects=parent_ir.effects,
    )
    body_glue = compile_ir(body_ir)
    body_payload = {
        "goal": body_glue.goal,
        "inputs": [field.model_dump() for field in body_glue.inputs],
        "outputs": [field.model_dump() for field in body_glue.outputs],
        "effects": list(body_glue.effects),
        "graph": body_glue.graph.model_dump(by_alias=True),
    }

    step = IRStep(
        name=block.name,
        skill_id="parallel.map",
        sources={
            "items": _resolve_block_source(block.collection, block_output_map),
            **external_sources,
        },
        config={
            "mode": "inline_graph",
            "body": body_payload,
            "item_inputs": item_inputs,
            "max_items": block.max_items,
            "include_trace": True,
            **block.config,
        },
    )
    outputs = {
        (block.name, output_name): IRSource(step=block.name, port=output_name)
        for output_name in block.final_outputs
    }
    return {"steps": [step], "outputs": outputs}


def _lower_branch_block(
    block: Any,
    *,
    parent_ir: PlanningIR,
    block_output_map: dict[tuple[str, str], IRSource],
) -> dict[str, Any]:
    if block.condition is None:
        raise InvalidBranchBlockError(block.name, "missing condition source")
    if not block.then_steps or not block.else_steps:
        raise InvalidBranchBlockError(block.name, "must declare both then_steps and else_steps")
    if not block.then_outputs or not block.else_outputs:
        raise InvalidBranchBlockError(block.name, "must declare both then_outputs and else_outputs")

    then_keys = set(block.then_outputs)
    else_keys = set(block.else_outputs)
    if then_keys != else_keys:
        raise InvalidBranchBlockError(block.name, "then_outputs and else_outputs must declare identical keys")

    condition = _resolve_block_source(block.condition, block_output_map)
    then_steps = _lower_branch_side(
        block.name,
        "then",
        block.then_steps,
        block.inputs,
        condition,
        False,
        block_output_map,
    )
    else_steps = _lower_branch_side(
        block.name,
        "else",
        block.else_steps,
        block.inputs,
        condition,
        True,
        block_output_map,
    )

    merge_steps: list[IRStep] = []
    outputs: dict[tuple[str, str], IRSource] = {}
    then_name_map = {step.name.split(f"{block.name}__then__", 1)[1]: step.name for step in then_steps}
    else_name_map = {step.name.split(f"{block.name}__else__", 1)[1]: step.name for step in else_steps}

    for output_name in sorted(then_keys):
        then_ref = block.then_outputs[output_name]
        else_ref = block.else_outputs[output_name]
        merge_name = f"{block.name}__merge__{output_name}"
        merge_steps.append(
            IRStep(
                name=merge_name,
                skill_id="fallback.try",
                sources={
                    "primary": IRSource(step=then_name_map[then_ref.step], port=then_ref.port),
                    "fallback": IRSource(step=else_name_map[else_ref.step], port=else_ref.port),
                },
            )
        )
        outputs[(block.name, output_name)] = IRSource(step=merge_name, port="result")

    return {"steps": [*then_steps, *else_steps, *merge_steps], "outputs": outputs}


def _lower_branch_side(
    block_name: str,
    side: str,
    steps: list[IRStep],
    input_map: dict[str, IRSource],
    condition: IRSource,
    unless: bool,
    block_output_map: dict[tuple[str, str], IRSource],
) -> list[IRStep]:
    local_names = {step.name for step in steps}
    prefixed: list[IRStep] = []
    for step in steps:
        if step.when is not None:
            raise InvalidBranchBlockError(block_name, "nested step.when inside branch blocks is not supported yet")
        sources: dict[str, IRSource] = {}
        for port, source in step.sources.items():
            sources[port] = _rewrite_branch_source(
                source,
                block_name=block_name,
                side=side,
                local_names=local_names,
                input_map=input_map,
                block_output_map=block_output_map,
            )
        prefixed.append(
            IRStep(
                name=f"{block_name}__{side}__{step.name}",
                skill_id=step.skill_id,
                version=step.version,
                sources=sources,
                config=step.config,
                when=condition,
                unless=unless,
            )
        )
    return prefixed


def _rewrite_branch_source(
    source: IRSource,
    *,
    block_name: str,
    side: str,
    local_names: set[str],
    input_map: dict[str, IRSource],
    block_output_map: dict[tuple[str, str], IRSource],
) -> IRSource:
    if source.binding is not None:
        return source
    if source.step == "input" and source.port in input_map:
        return _resolve_block_source(input_map[source.port], block_output_map)
    if source.step in local_names:
        return IRSource(step=f"{block_name}__{side}__{source.step}", port=source.port)
    return _resolve_block_source(source, block_output_map)


def _resolve_block_source(
    source: IRSource,
    block_output_map: dict[tuple[str, str], IRSource],
) -> IRSource:
    if source.binding is not None or source.step is None or source.port is None:
        return source
    return block_output_map.get((source.step, source.port), source)


def _rewrite_step_block_sources(
    step: IRStep,
    block_output_map: dict[tuple[str, str], IRSource],
) -> IRStep:
    sources = {
        port: _resolve_block_source(source, block_output_map)
        for port, source in step.sources.items()
    }
    when = _resolve_block_source(step.when, block_output_map) if step.when is not None else None
    return step.model_copy(update={"sources": sources, "when": when})


def _rewrite_output_ref(
    ref: IROutputRef,
    block_output_map: dict[tuple[str, str], IRSource],
) -> IROutputRef:
    source = block_output_map.get((ref.step, ref.port))
    if source is None or source.step is None or source.port is None:
        return ref
    return IROutputRef(step=source.step, port=source.port)


def _expand_bindings(ir: PlanningIR) -> PlanningIR:
    if not ir.bindings:
        return ir

    binding_map = {binding.name: binding.source for binding in ir.bindings}
    new_steps: list[IRStep] = []
    for step in ir.steps:
        sources: dict[str, IRSource] = {}
        for port, source in step.sources.items():
            if source.binding is not None:
                resolved = binding_map[source.binding]
                sources[port] = IRSource(step=resolved.step, port=resolved.port)
            else:
                sources[port] = source
        when = step.when
        if when is not None and when.binding is not None:
            resolved = binding_map[when.binding]
            when = IRSource(step=resolved.step, port=resolved.port)
        new_steps.append(step.model_copy(update={"sources": sources, "when": when}))

    return ir.model_copy(update={"steps": new_steps})


def _validate_source_reference(
    source: IRSource,
    *,
    step_name: str,
    source_port: str,
    input_names: set[str],
    step_names: set[str],
    binding_names: set[str],
) -> None:
    if source.binding is not None:
        if source.binding not in binding_names:
            raise UnknownBindingError(step_name, source_port, source.binding)
        return

    if source.step is None or source.port is None:
        raise CompilerError(
            f"Source for '{step_name}.{source_port}' must include step/port or binding",
            phase="validate_ir",
            details={"step_name": step_name, "source_port": source_port},
        )

    if source.step == "input":
        if source.port not in input_names:
            raise UnknownInputError(step_name, source_port, source.port)
    elif source.step == step_name:
        raise SelfLoopError(step_name, source_port)
    elif source.step not in step_names:
        raise UnknownSourceStepError(step_name, source_port, source.step)


def _check_dag(ir: PlanningIR) -> None:
    """Verify the step dependency graph is acyclic (Kahn's algorithm)."""
    step_names = [s.name for s in ir.steps]
    # Build adjacency: step -> set of steps it depends on
    deps: dict[str, set[str]] = {s.name: set() for s in ir.steps}
    for step in ir.steps:
        for source in step.sources.values():
            if source.step != "input":
                deps[step.name].add(source.step)

    # Kahn's
    in_degree = {name: len(d) for name, d in deps.items()}
    queue = [name for name, deg in in_degree.items() if deg == 0]
    visited: list[str] = []

    while queue:
        node = queue.pop(0)
        visited.append(node)
        for name, d in deps.items():
            if node in d:
                in_degree[name] -= 1
                if in_degree[name] == 0:
                    queue.append(name)

    if len(visited) != len(step_names):
        remaining = [n for n in step_names if n not in visited]
        raise CycleError(remaining)


def _normalize_type(type_val: Any) -> Any:
    """Normalize an IR-declared type to a valid Graphsmith type.

    String types outside the supported grammar (e.g. 'json', 'text') fall back
    to 'string'. Structured type mappings are preserved for downstream validation.
    """
    if isinstance(type_val, dict):
        return type_val
    if not isinstance(type_val, str):
        return "string"
    if is_supported_type_spec(type_val):
        return type_val
    return "string"


def _normalize_skill_id(skill_id: str, version: str) -> tuple[str, str]:
    """Strip @version suffix from skill_id if present."""
    if "@" in skill_id:
        base, _, ver = skill_id.partition("@")
        return base, ver or version
    return skill_id, version


def _build_nodes(ir: PlanningIR) -> list[GraphNode]:
    """Generate GraphNodes from IR steps."""
    nodes: list[GraphNode] = []
    for step in ir.steps:
        config: dict[str, Any] = {}
        skill_id, version = _normalize_skill_id(step.skill_id, step.version)

        if skill_id in PRIMITIVE_OPS:
            # Primitive op: skill_id IS the op, merge config directly
            op = skill_id
            config = dict(step.config)
        else:
            # Skill invocation
            op = "skill.invoke"
            config = {
                "skill_id": skill_id,
                "version": version,
                **step.config,
            }

        when = None
        if step.when is not None:
            when = _source_to_condition_address(step.when, negate=step.unless)

        nodes.append(GraphNode(id=step.name, op=op, config=config, when=when))
    return nodes


def _remap_source(source: IRSource | None, name_map: dict[str, str]) -> IRSource | None:
    if source is None or source.binding is not None or source.step == "input":
        return source
    return IRSource(step=name_map.get(source.step, source.step), port=source.port)


def _source_to_condition_address(source: IRSource, *, negate: bool = False) -> str:
    prefix = "!" if negate else ""
    if source.step == "input":
        return f"{prefix}input.{source.port}"
    return f"{prefix}{source.step}.{source.port}"


def _build_edges(ir: PlanningIR) -> list[GraphEdge]:
    """Generate GraphEdges from IR step sources."""
    edges: list[GraphEdge] = []
    for step in ir.steps:
        for port, source in step.sources.items():
            if source.step == "input":
                from_addr = f"input.{source.port}"
            else:
                from_addr = f"{source.step}.{source.port}"
            to_addr = f"{step.name}.{port}"
            edges.append(GraphEdge(from_=from_addr, to=to_addr))
    return edges


def _build_graph_outputs(ir: PlanningIR) -> dict[str, str]:
    """Generate graph_outputs mapping from IR final_outputs."""
    return {
        name: f"{ref.step}.{ref.port}"
        for name, ref in ir.final_outputs.items()
    }


def _build_output_fields(ir: PlanningIR) -> list[IOField]:
    """Generate output IOFields from IR final_outputs.

    Uses 'string' as default type since the IR doesn't carry output types.
    The downstream validator will catch type mismatches.
    """
    return [IOField(name=name, type="string") for name in ir.final_outputs]
