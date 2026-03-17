"""array.map and array.filter ops — sequential collection operations."""
from __future__ import annotations

import re
from typing import Any

from graphsmith.exceptions import OpError


def array_map(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Map over an array, extracting a field or applying a template.

    Inputs:
        items (list): The source array.

    Config (exactly one of):
        field (str): Extract this field from each dict item.
        template (str): Render this template for each item ({{item}} placeholder).

    Returns:
        {"mapped": [<results>]}
    """
    items = inputs.get("items")
    if items is None:
        raise OpError("array.map requires input 'items'")
    if not isinstance(items, list):
        raise OpError(f"array.map: 'items' must be a list, got {type(items).__name__}")

    field = config.get("field")
    template = config.get("template")

    if field and template:
        raise OpError("array.map: provide 'field' or 'template' in config, not both")
    if not field and not template:
        raise OpError("array.map: config must include 'field' or 'template'")

    if field:
        mapped = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise OpError(
                    f"array.map: item at index {i} is not a dict (field mode requires dicts)"
                )
            if field not in item:
                raise OpError(
                    f"array.map: item at index {i} has no field '{field}'"
                )
            mapped.append(item[field])
        return {"mapped": mapped}

    # Template mode
    def _render(item: Any) -> str:
        return re.sub(r"\{\{item\}\}", str(item), template)

    return {"mapped": [_render(item) for item in items]}


def array_filter(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Filter an array by a field predicate.

    Inputs:
        items (list): The source array (items must be dicts).

    Config:
        field (str): Field name to check on each item.
        value (Any, optional): If set, keep items where item[field] == value.
                               If not set, keep items where item[field] is truthy.

    Returns:
        {"filtered": [<matching items>]}
    """
    items = inputs.get("items")
    if items is None:
        raise OpError("array.filter requires input 'items'")
    if not isinstance(items, list):
        raise OpError(f"array.filter: 'items' must be a list, got {type(items).__name__}")

    field = config.get("field")
    if not field:
        raise OpError("array.filter requires config.field")

    has_value = "value" in config
    target = config.get("value")

    filtered = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if field not in item:
            continue
        if has_value:
            if item[field] == target:
                filtered.append(item)
        else:
            if item[field]:
                filtered.append(item)

    return {"filtered": filtered}
