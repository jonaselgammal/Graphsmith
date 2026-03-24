"""Common Pydantic models."""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class IOField(BaseModel):
    """Input or output field contract.

    `type` accepts either:
    - a scalar/parameterised type string such as `string`, `array<string>`,
      `union<string, integer>`, `record<object>`, `ref<User>`
    - a structured mapping such as
      `{"type": "object", "properties": {"name": "string"}}`
    """

    name: str
    type: Any
    required: bool = True
    description: Optional[str] = None


class ExampleCase(BaseModel):
    """One example input/output pair."""

    name: str
    input: dict[str, Any]
    expected_output: dict[str, Any] | None = None
