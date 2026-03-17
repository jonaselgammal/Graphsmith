"""select.fields op — pick named fields from an object."""
from __future__ import annotations

from typing import Any

from graphsmith.exceptions import OpError


def select_fields(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Select named fields from the input object.

    Config:
        fields (list[str]): Field names to keep.

    Inputs:
        data (dict): The object to select from.

    Returns:
        {"selected": <dict with only the requested fields>}
    """
    fields = config.get("fields")
    if not fields or not isinstance(fields, list):
        raise OpError("select.fields requires config.fields (list of strings)")

    data = inputs.get("data")
    if data is None:
        raise OpError("select.fields requires input 'data'")
    if not isinstance(data, dict):
        raise OpError(f"select.fields: 'data' must be a dict, got {type(data).__name__}")

    selected = {k: data[k] for k in fields if k in data}
    return {"selected": selected}
