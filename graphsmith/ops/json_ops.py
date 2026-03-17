"""json.parse op — parse a JSON string into a Python object."""
from __future__ import annotations

import json
from typing import Any

from graphsmith.exceptions import OpError


def json_parse(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Parse a JSON string.

    Inputs:
        text (str): The JSON string to parse.

    Returns:
        {"parsed": <Any>}
    """
    text = inputs.get("text")
    if text is None:
        raise OpError("json.parse requires input 'text'")
    if not isinstance(text, str):
        raise OpError(f"json.parse: 'text' must be a string, got {type(text).__name__}")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OpError(f"json.parse: invalid JSON — {exc}") from exc
    return {"parsed": parsed}
