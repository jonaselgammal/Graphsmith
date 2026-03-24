"""parallel.map op — bounded sequential collection execution.

Applies an inner op or skill to each item in an array. Execution remains
strictly sequential and deterministic in v1, but the surface now supports
reusable skills as the loop body.
"""
from __future__ import annotations

from typing import Any

from graphsmith.exceptions import OpError

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

    inner_op = config.get("op")
    if not inner_op or not isinstance(inner_op, str):
        raise OpError("parallel.map requires config.op (string naming an inner op)")

    if inner_op == "parallel.map":
        raise OpError("parallel.map does not support nesting in v1.")

    item_input = config.get("item_input", "item")
    if not isinstance(item_input, str) or not item_input:
        raise OpError("parallel.map: config.item_input must be a non-empty string")

    max_items = config.get("max_items", DEFAULT_MAX_ITEMS)
    if not isinstance(max_items, int) or max_items < 0:
        raise OpError("parallel.map: config.max_items must be a non-negative integer")
    if len(items) > max_items:
        raise OpError(
            f"parallel.map: item count {len(items)} exceeds configured limit {max_items}"
        )

    # Late import to avoid circular dependency
    from graphsmith.ops.registry import _PURE_OPS
    from graphsmith.ops.skill_invoke import skill_invoke

    if inner_op != "skill.invoke" and inner_op not in _PURE_OPS:
        raise OpError(
            f"parallel.map: inner op '{inner_op}' is not supported. "
            f"Supported: skill.invoke, {', '.join(sorted(_PURE_OPS))}"
        )

    op_config = config.get("op_config", {})
    if not isinstance(op_config, dict):
        raise OpError("parallel.map: config.op_config must be an object when provided")

    passthrough_inputs = {k: v for k, v in inputs.items() if k != "items"}

    results: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        inner_inputs = dict(passthrough_inputs)
        inner_inputs["item"] = item
        inner_inputs[item_input] = item
        try:
            if inner_op == "skill.invoke":
                out, _child_trace = skill_invoke(
                    op_config,
                    inner_inputs,
                    registry=registry,
                    llm_provider=llm_provider,
                    depth=depth,
                    call_stack=call_stack or [],
                )
            else:
                op_fn = _PURE_OPS[inner_op]
                out = op_fn(op_config, inner_inputs)
        except OpError as exc:
            raise OpError(
                f"parallel.map: inner op '{inner_op}' failed on item {i}: {exc}"
            ) from exc
        results.append(out)

    return {"results": results}
