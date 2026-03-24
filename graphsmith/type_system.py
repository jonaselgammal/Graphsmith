"""Shared type-system helpers for contracts and planner/compiler validation."""
from __future__ import annotations

import re
from typing import Any

from graphsmith.exceptions import ValidationError


BASE_TYPES: set[str] = {
    "string",
    "integer",
    "number",
    "boolean",
    "bytes",
    "object",
}

PARAMETERIZED_SINGLE = {"array", "optional", "record", "ref"}
PARAMETERIZED_MULTI = {"union"}

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")


def validate_type_spec(type_val: Any, *, context: str) -> None:
    """Validate a type spec expressed as a string or structured mapping."""
    if isinstance(type_val, dict):
        _validate_structured_type(type_val, context=context)
        return
    if not isinstance(type_val, str):
        raise ValidationError(
            f"Type must be a string or object mapping in {context}, got {type(type_val).__name__}"
        )
    _validate_type_expr(type_val, context=context)


def is_supported_type_expr(type_val: str) -> bool:
    """Return True when a string type expression uses supported syntax."""
    try:
        _validate_type_expr(type_val, context="type expression")
    except ValidationError:
        return False
    return True


def is_supported_type_spec(type_val: Any) -> bool:
    """Return True when a type spec is valid under the current grammar."""
    try:
        validate_type_spec(type_val, context="type spec")
    except ValidationError:
        return False
    return True


def _validate_structured_type(data: dict[str, Any], *, context: str) -> None:
    type_name = data.get("type")
    if not isinstance(type_name, str):
        raise ValidationError(
            f"Structured type in {context} must include string key 'type'"
        )

    if type_name in BASE_TYPES:
        if type_name == "object":
            properties = data.get("properties", {})
            if properties is not None:
                if not isinstance(properties, dict):
                    raise ValidationError(
                        f"Structured object type in {context} has non-object 'properties'"
                    )
                for prop_name, prop_type in properties.items():
                    validate_type_spec(prop_type, context=f"{context}.properties['{prop_name}']")

            required = data.get("required", [])
            if required is not None:
                if not isinstance(required, list) or not all(isinstance(x, str) for x in required):
                    raise ValidationError(
                        f"Structured object type in {context} has invalid 'required' list"
                    )

            if "additional_properties" in data:
                validate_type_spec(
                    data["additional_properties"],
                    context=f"{context}.additional_properties",
                )
        return

    if type_name == "array":
        if "items" not in data:
            raise ValidationError(f"Structured array type in {context} requires 'items'")
        validate_type_spec(data["items"], context=f"{context}.items")
        return

    if type_name == "union":
        any_of = data.get("any_of")
        if not isinstance(any_of, list) or len(any_of) < 2:
            raise ValidationError(
                f"Structured union type in {context} requires 'any_of' with at least two variants"
            )
        for i, item in enumerate(any_of):
            validate_type_spec(item, context=f"{context}.any_of[{i}]")
        return

    if type_name == "ref":
        name = data.get("name")
        if not isinstance(name, str) or not _IDENT_RE.match(name):
            raise ValidationError(
                f"Structured ref type in {context} requires valid string 'name'"
            )
        return

    raise ValidationError(
        f"Unknown structured type '{type_name}' in {context}. "
        "Supported structured types: object, array, union, ref."
    )


def _validate_type_expr(type_expr: str, *, context: str) -> None:
    raw = type_expr.strip()
    if not raw:
        raise ValidationError(f"Empty type in {context}")

    if "<" not in raw and ">" not in raw:
        if raw not in BASE_TYPES:
            raise ValidationError(
                f"Unknown type '{raw}' in {context}. "
                f"Allowed base types: {', '.join(sorted(BASE_TYPES))}"
            )
        return

    outer, inner = _split_parameterized(raw, context=context)
    if outer in PARAMETERIZED_SINGLE:
        if outer == "ref":
            if not _IDENT_RE.match(inner):
                raise ValidationError(
                    f"ref<T> in {context} requires a valid schema name, got '{inner}'"
                )
            return
        validate_type_spec(inner, context=f"{context} ({outer} item)")
        return

    if outer in PARAMETERIZED_MULTI:
        parts = _split_top_level(inner, separator=",")
        if len(parts) < 2:
            raise ValidationError(
                f"{outer}<...> in {context} requires at least two member types"
            )
        for i, part in enumerate(parts):
            validate_type_spec(part.strip(), context=f"{context} ({outer} member {i})")
        return

    raise ValidationError(
        f"Unknown parameterised type '{outer}' in {context}. "
        "Supported parameterised types: array<T>, optional<T>, union<T1,T2>, "
        "record<T>, ref<SchemaName>."
    )


def _split_parameterized(type_expr: str, *, context: str) -> tuple[str, str]:
    open_idx = type_expr.find("<")
    if open_idx <= 0 or not type_expr.endswith(">"):
        raise ValidationError(f"Malformed parameterised type '{type_expr}' in {context}")
    outer = type_expr[:open_idx].strip()
    inner = type_expr[open_idx + 1 : -1].strip()
    if not inner:
        raise ValidationError(f"Malformed parameterised type '{type_expr}' in {context}")
    if _has_unbalanced_angles(inner):
        raise ValidationError(f"Malformed parameterised type '{type_expr}' in {context}")
    return outer, inner


def _split_top_level(text: str, *, separator: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in text:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == separator and depth == 0:
            piece = "".join(current).strip()
            if not piece:
                raise ValidationError(f"Malformed list in type expression '{text}'")
            parts.append(piece)
            current = []
            continue
        current.append(ch)

    if depth != 0:
        raise ValidationError(f"Malformed type expression '{text}'")

    piece = "".join(current).strip()
    if not piece:
        raise ValidationError(f"Malformed list in type expression '{text}'")
    parts.append(piece)
    return parts


def _has_unbalanced_angles(text: str) -> bool:
    depth = 0
    for ch in text:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
            if depth < 0:
                return True
    return depth != 0
