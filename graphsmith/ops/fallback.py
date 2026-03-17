"""fallback.try op — try a primary value, fall back to an alternative."""
from __future__ import annotations

from typing import Any


def fallback_try(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Return *primary* if it is not None, otherwise return *fallback*.

    Inputs:
        primary (Any | None): The preferred value.
        fallback (Any): The fallback value.

    Returns:
        {"result": <selected value>}
    """
    primary = inputs.get("primary")
    if primary is not None:
        return {"result": primary}
    return {"result": inputs.get("fallback")}
