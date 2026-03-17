"""Combined skill package model."""
from __future__ import annotations

from pydantic import BaseModel, Field

from graphsmith.models.common import ExampleCase
from graphsmith.models.graph import GraphBody
from graphsmith.models.skill import SkillMetadata


class ExamplesFile(BaseModel):
    """Examples file model."""

    examples: list[ExampleCase] = Field(default_factory=list)


class SkillPackage(BaseModel):
    """Combined parsed package."""

    root_path: str
    skill: SkillMetadata
    graph: GraphBody
    examples: ExamplesFile
