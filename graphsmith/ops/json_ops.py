"""JSON ops — parse and assemble JSON payloads."""
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


def json_pack(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Pack arbitrary scalar inputs into a JSON object string.

    Inputs:
        Any input ports become fields in the packed object unless the value is None.

    Config:
        static_fields (dict, optional): Additional constant fields to merge in.

    Returns:
        {"raw_json": <JSON string>}
    """
    static_fields = config.get("static_fields", {})
    if static_fields is None:
        static_fields = {}
    if not isinstance(static_fields, dict):
        raise OpError("json.pack: config.static_fields must be a dict")

    payload: dict[str, Any] = {}
    for key, value in inputs.items():
        if value is not None:
            payload[key] = value
    payload.update(static_fields)
    return {"raw_json": json.dumps(payload)}
