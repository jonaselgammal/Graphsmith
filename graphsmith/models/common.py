"""Common Pydantic models."""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class IOField(BaseModel):
    """Input or output field contract."""

    name: str
    type: Any
    required: bool = True
    description: Optional[str] = None


class ExampleCase(BaseModel):
    """One example input/output pair."""

    name: str
    input: dict[str, Any]
    expected_output: dict[str, Any] | None = None
