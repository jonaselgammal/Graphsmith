"""Planning IR — semantic intermediate representation between LLM and graph.

The IR captures WHAT the plan does (steps, data flow, config) without
requiring the LLM to serialize exact graph structures (node IDs, edge
syntax, graph_outputs mapping). The deterministic compiler in
compiler.py lowers IR → GlueGraph.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IRInput(BaseModel):
    """A graph-level input declared by the plan."""

    name: str
    type: str = "string"


class IRSource(BaseModel):
    """Where a step gets one of its inputs.

    step="input" means a graph-level input; otherwise it names another step.
    """

    step: str
    port: str


class IRStep(BaseModel):
    """One semantic step in the plan.

    The compiler maps each step to a GraphNode + edges.
    """

    name: str
    skill_id: str  # e.g. "text.extract_keywords.v1" or "template.render"
    version: str = "1.0.0"
    sources: dict[str, IRSource] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class IROutputRef(BaseModel):
    """Reference to a step output that becomes a graph-level output."""

    step: str
    port: str


class PlanningIR(BaseModel):
    """Semantic planning intermediate representation.

    This is what the LLM emits. The compiler deterministically lowers
    it to a GlueGraph without any LLM involvement.
    """

    goal: str
    inputs: list[IRInput]
    steps: list[IRStep]
    final_outputs: dict[str, IROutputRef]
    effects: list[str] = Field(default_factory=lambda: ["pure"])
    reasoning: str = ""
