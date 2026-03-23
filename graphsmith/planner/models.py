"""Typed models for planner input, output, and glue graphs."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.planner.candidates import RetrievalDiagnostics
from graphsmith.registry.index import IndexEntry


# ── planner request ──────────────────────────────────────────────────


class PlanRequest(BaseModel):
    """Everything the planner needs to compose a glue graph."""

    goal: str
    candidates: list[IndexEntry]
    constraints: list[str] = Field(default_factory=list)
    desired_outputs: list[IOField] = Field(default_factory=list)


# ── glue graph ───────────────────────────────────────────────────────


class GlueGraph(BaseModel):
    """A task-specific composed graph — not a reusable skill.

    Contains enough metadata to be validated via a synthetic SkillPackage.
    """

    goal: str
    inputs: list[IOField]
    outputs: list[IOField]
    effects: list[str] = Field(default_factory=list)
    graph: GraphBody


# ── unresolved holes ─────────────────────────────────────────────────


class UnresolvedHole(BaseModel):
    """One gap in a partially composed plan."""

    node_id: str
    kind: Literal[
        "missing_skill",
        "ambiguous_candidate",
        "missing_output_path",
        "unsupported_op",
        "validation_error",
    ]
    description: str
    candidates: list[str] = Field(default_factory=list)


# ── planner result ───────────────────────────────────────────────────


class PlanResult(BaseModel):
    """Structured planner output — always typed, never raw text."""

    status: Literal["success", "partial", "failure"]
    graph: GlueGraph | None = None
    holes: list[UnresolvedHole] = Field(default_factory=list)
    reasoning: str = ""
    candidates_considered: list[str] = Field(default_factory=list)
    retrieval: RetrievalDiagnostics | None = None
