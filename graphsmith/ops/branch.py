"""branch.if op — conditional value selection."""
from __future__ import annotations

from typing import Any

from graphsmith.exceptions import OpError


def branch_if(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Return one of two values based on a boolean condition.

    Inputs:
        condition (bool): The branch condition.
        then_value (Any): Value returned when condition is truthy.
        else_value (Any): Value returned when condition is falsy.

    Returns:
        {"result": <selected value>}
    """
    condition = inputs.get("condition")
    if condition is None:
        raise OpError("branch.if requires input 'condition'")

    if condition:
        return {"result": inputs.get("then_value")}
    else:
        return {"result": inputs.get("else_value")}
