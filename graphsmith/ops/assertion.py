"""assert.check op — fail-fast guard on a boolean condition."""
from __future__ import annotations

from typing import Any

from graphsmith.exceptions import OpError


def assert_check(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Check a boolean condition; raise on failure.

    Config:
        message (str, optional): Custom error message on failure.

    Inputs:
        condition (bool): The condition to check.
        value (Any, optional): A pass-through value returned on success.

    Returns:
        {"value": <the pass-through value, or True>}
    """
    condition = inputs.get("condition")
    if condition is None:
        raise OpError("assert.check requires input 'condition'")

    if not condition:
        msg = config.get("message", "Assertion failed")
        raise OpError(f"assert.check: {msg}")

    return {"value": inputs.get("value", True)}
