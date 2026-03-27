"""parallel.map op — bounded sequential collection execution.

Applies an inner op or skill to each item in an array. Execution remains
strictly sequential and deterministic in v1, but the surface now supports
reusable skills as the loop body.
"""
from __future__ import annotations

from typing import Any

from graphsmith.exceptions import ExecutionError, OpError
from graphsmith.traces.models import NodeTrace, RunTrace, _now_iso

DEFAULT_MAX_ITEMS = 100


def parallel_map(
    config: dict[str, Any],
    inputs: dict[str, Any],
    *,
    registry: Any | None = None,
    llm_provider: Any | None = None,
    depth: int = 0,
    call_stack: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Map an inner op over an array, sequentially.

    Config:
        op (str): Primitive op or skill.invoke to apply per item.
        op_config (dict, optional): Static config for the inner op.
        item_input (str, optional): Inner input name that receives the current item.
                                    Defaults to "item".
        item_inputs (list[str], optional): Alternative to item_input for inline loop bodies.
        body (dict, optional): Inline executable body used when op=parallel.map loop lowering.
        max_items (int, optional): Hard cap on number of items processed.

    Inputs:
        items (list): The source array.
        Any additional inputs are passed through to each inner invocation.

    Returns:
        {"results": [<inner op output dict for each item>]}
    """
    items = inputs.get("items")
    if items is None:
        raise OpError("parallel.map requires input 'items'")
    if not isinstance(items, list):
        raise OpError(f"parallel.map: 'items' must be a list, got {type(items).__name__}")

    mode = config.get("mode", "op")
    inner_op = config.get("op")
    if mode == "inline_graph":
        inner_op = "__inline_graph__"
    if not inner_op or not isinstance(inner_op, str):
        raise OpError("parallel.map requires config.op (string naming an inner op)")

    if inner_op == "parallel.map":
        raise OpError("parallel.map does not support nesting in v1.")

    item_inputs_raw = config.get("item_inputs")
    if item_inputs_raw is None:
        item_input = config.get("item_input", "item")
        if not isinstance(item_input, str) or not item_input:
            raise OpError("parallel.map: config.item_input must be a non-empty string")
        item_inputs = [item_input]
    else:
        if not isinstance(item_inputs_raw, list) or not item_inputs_raw or not all(isinstance(x, str) and x for x in item_inputs_raw):
            raise OpError("parallel.map: config.item_inputs must be a non-empty list of strings")
        item_inputs = item_inputs_raw

    max_items = config.get("max_items", DEFAULT_MAX_ITEMS)
    if not isinstance(max_items, int) or max_items < 0:
        raise OpError("parallel.map: config.max_items must be a non-negative integer")
    if len(items) > max_items:
        raise OpError(
            f"parallel.map: item count {len(items)} exceeds configured limit {max_items}"
        )

    include_trace = bool(config.get("include_trace", False))
    aggregate_outputs = bool(config.get("aggregate_outputs", False))

    # Late import to avoid circular dependency
    from graphsmith.ops.registry import _PURE_OPS
    from graphsmith.ops.skill_invoke import skill_invoke

    if inner_op not in {"skill.invoke", "__inline_graph__"} and inner_op not in _PURE_OPS:
        raise OpError(
            f"parallel.map: inner op '{inner_op}' is not supported. "
            f"Supported: skill.invoke, {', '.join(sorted(_PURE_OPS))}"
        )

    op_config = config.get("op_config", {})
    if not isinstance(op_config, dict):
        raise OpError("parallel.map: config.op_config must be an object when provided")

    passthrough_inputs = {k: v for k, v in inputs.items() if k != "items"}

    results: list[dict[str, Any]] = []
    aggregated: dict[str, list[Any]] = {}
    trace = RunTrace(
        skill_id="parallel.map",
        started_at=_now_iso(),
        inputs_summary={"item_count": len(items)},
    ) if include_trace else None
    for i, item in enumerate(items):
        inner_inputs = dict(passthrough_inputs)
        inner_inputs["item"] = item
        for item_input in item_inputs:
            inner_inputs[item_input] = item
        child_trace = None
        started = _now_iso()
        try:
            if inner_op == "__inline_graph__":
                out, child_trace = _run_inline_body(
                    config,
                    inner_inputs,
                    registry=registry,
                    llm_provider=llm_provider,
                    depth=depth,
                    call_stack=call_stack or [],
                )
            elif inner_op == "skill.invoke":
                out, _child_trace = skill_invoke(
                    op_config,
                    inner_inputs,
                    registry=registry,
                    llm_provider=llm_provider,
                    depth=depth,
                    call_stack=call_stack or [],
                )
                child_trace = _child_trace
            else:
                op_fn = _PURE_OPS[inner_op]
                out = op_fn(op_config, inner_inputs)
        except (OpError, ExecutionError) as exc:
            if trace is not None:
                trace.nodes.append(NodeTrace(
                    node_id=f"item_{i}",
                    op=inner_op,
                    status="error",
                    started_at=started,
                    ended_at=_now_iso(),
                    inputs_summary={"item": item},
                    error=str(exc),
                ))
                trace.status = "error"
                trace.error = str(exc)
                trace.ended_at = _now_iso()
            raise OpError(
                f"parallel.map: inner op '{inner_op}' failed on item {i}: {exc}",
                trace=trace,
            ) from exc
        results.append(out)
        for key, value in out.items():
            aggregated.setdefault(key, []).append(value)
        if trace is not None:
            trace.nodes.append(NodeTrace(
                node_id=f"item_{i}",
                op=inner_op,
                status="ok",
                started_at=started,
                ended_at=_now_iso(),
                inputs_summary={"item": item},
                outputs_summary=out,
                child_trace=child_trace,
            ))

    outputs: dict[str, Any] = {"results": results}
    if mode == "inline_graph" or aggregate_outputs:
        outputs.update(aggregated)
    if trace is None:
        return outputs
    trace.status = "ok"
    trace.ended_at = _now_iso()
    trace.outputs_summary = {k: f"{len(v)} item(s)" for k, v in aggregated.items()}
    return outputs, trace


def _run_inline_body(
    config: dict[str, Any],
    inputs: dict[str, Any],
    *,
    registry: Any | None,
    llm_provider: Any | None,
    depth: int,
    call_stack: list[tuple[str, str]],
) -> tuple[dict[str, Any], Any]:
    body = config.get("body")
    if not isinstance(body, dict):
        raise OpError("parallel.map inline_graph requires config.body object")

    from graphsmith.models.package import ExamplesFile, SkillPackage
    from graphsmith.models.skill import SkillMetadata
    from graphsmith.models.graph import GraphBody
    from graphsmith.runtime.executor import run_skill_package
    from graphsmith.validator import validate_skill_package

    skill = SkillMetadata(
        id=f"_inline.loop.{body.get('goal', 'body')}",
        name=f"Inline loop body: {body.get('goal', 'body')}",
        version="0.0.0",
        description=body.get("goal", "inline loop body"),
        inputs=body.get("inputs", []),
        outputs=body.get("outputs", []),
        effects=body.get("effects", ["pure"]),
    )
    graph = GraphBody.model_validate(body.get("graph", {}))
    pkg = SkillPackage(
        root_path="(inline_loop)",
        skill=skill,
        graph=graph,
        examples=ExamplesFile(),
    )
    validate_skill_package(pkg)
    result = run_skill_package(
        pkg,
        inputs,
        llm_provider=llm_provider,
        registry=registry,
        _depth=depth + 1,
        _call_stack=call_stack,
    )
    return result.outputs, result.trace
