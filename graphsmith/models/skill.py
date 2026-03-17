"""Skill contract models."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from graphsmith.models.common import IOField


class QualityInfo(BaseModel):
    """Optional skill quality metadata."""

    latency_ms_p50: int | None = None
    success_rate: float | None = None


class SkillMetadata(BaseModel):
    """Top-level skill metadata from skill.yaml."""

    id: str
    name: str
    version: str
    description: str
    inputs: list[IOField]
    outputs: list[IOField]
    effects: list[str]
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    quality: QualityInfo | None = None
    authors: list[str] = Field(default_factory=list)
    license: str | None = None
    homepage: str | None = None
