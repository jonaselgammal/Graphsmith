"""Executable graph models."""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    """One graph node."""

    id: str
    op: str
    inputs: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    when: str | None = None
    retry: int | None = None
    timeout_ms: int | None = None


class GraphEdge(BaseModel):
    """One graph edge from source address to destination address."""

    model_config = {"populate_by_name": True}

    from_: str = Field(alias="from")
    to: str


class GraphBody(BaseModel):
    """Graph body from graph.yaml."""

    version: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    outputs: dict[str, str]
