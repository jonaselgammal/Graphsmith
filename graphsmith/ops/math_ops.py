"""Pure math ops: add, multiply, mean."""
from __future__ import annotations

from typing import Any

from graphsmith.exceptions import OpError


def _to_number(value: Any, name: str) -> float:
    """Convert a value to float, with a clear error."""
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise OpError(f"{name}: cannot convert {value!r} to number") from exc


def math_add(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Add two numbers.

    Inputs: a, b (number or string-encoded number)
    Returns: {"result": <str>}
    """
    a = _to_number(inputs.get("a", 0), "math.add")
    b = _to_number(inputs.get("b", 0), "math.add")
    result = a + b
    return {"result": str(int(result) if result == int(result) else result)}


def math_multiply(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Multiply two numbers.

    Inputs: a, b (number or string-encoded number)
    Returns: {"result": <str>}
    """
    a = _to_number(inputs.get("a", 0), "math.multiply")
    b = _to_number(inputs.get("b", 0), "math.multiply")
    result = a * b
    return {"result": str(int(result) if result == int(result) else result)}


def math_mean(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Compute the mean of newline-separated numbers.

    Inputs: values (str, newline-separated numbers)
    Returns: {"result": <str>}
    """
    raw = inputs.get("values", "")
    if not raw or not str(raw).strip():
        raise OpError("math.mean requires non-empty input 'values'")
    parts = [p.strip() for p in str(raw).split("\n") if p.strip()]
    numbers = [_to_number(p, "math.mean") for p in parts]
    if not numbers:
        raise OpError("math.mean: no valid numbers found")
    result = sum(numbers) / len(numbers)
    return {"result": str(int(result) if result == int(result) else result)}
