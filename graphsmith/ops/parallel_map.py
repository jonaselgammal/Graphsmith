"""parallel.map op — sequential fallback with parallel interface.

Applies an inner primitive op to each item in an array.
Execution is strictly sequential in v1.
"""
from __future__ import annotations

from typing import Any

from graphsmith.exceptions import OpError


def parallel_map(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Map an inner op over an array, sequentially.

    Config:
        op (str): Primitive op to apply per item.
        op_config (dict, optional): Static config for the inner op.

    Inputs:
        items (list): The source array.

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
        raise OpError("parallel.map requires config.op (string naming a primitive op)")

    if inner_op == "skill.invoke":
        raise OpError(
            "parallel.map does not support skill.invoke in v1. "
            "Use array.map for simple transformations, or wire skill.invoke nodes manually."
        )
    if inner_op == "parallel.map":
        raise OpError("parallel.map does not support nesting in v1.")

    # Late import to avoid circular dependency
    from graphsmith.ops.registry import _PURE_OPS

    if inner_op not in _PURE_OPS:
        raise OpError(
            f"parallel.map: inner op '{inner_op}' is not a supported pure op. "
            f"Supported: {', '.join(sorted(_PURE_OPS))}"
        )

    op_fn = _PURE_OPS[inner_op]
    op_config = config.get("op_config", {})

    results: list[dict[str, Any]] = []
    for i, item in enumerate(items):
        try:
            out = op_fn(op_config, {"item": item})
        except OpError as exc:
            raise OpError(
                f"parallel.map: inner op '{inner_op}' failed on item {i}: {exc}"
            ) from exc
        results.append(out)

    return {"results": results}
