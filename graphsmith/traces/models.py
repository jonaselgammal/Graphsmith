"""Trace data models for recording graph execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class NodeTrace:
    """Execution trace for a single node."""

    node_id: str
    op: str
    status: str  # "ok" | "error" | "skipped"
    started_at: str
    ended_at: str
    inputs_summary: dict[str, Any] = field(default_factory=dict)
    outputs_summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    child_trace: RunTrace | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "node_id": self.node_id,
            "op": self.op,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "inputs_summary": self.inputs_summary,
            "outputs_summary": self.outputs_summary,
        }
        if self.error:
            d["error"] = self.error
        if self.child_trace:
            d["child_trace"] = self.child_trace.to_dict()
        return d


@dataclass
class RunTrace:
    """Execution trace for a full graph run."""

    skill_id: str
    started_at: str
    ended_at: str | None = None
    status: str = "running"
    nodes: list[NodeTrace] = field(default_factory=list)
    inputs_summary: dict[str, Any] = field(default_factory=dict)
    outputs_summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "skill_id": self.skill_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "nodes": [n.to_dict() for n in self.nodes],
            "inputs_summary": self.inputs_summary,
            "outputs_summary": self.outputs_summary,
        }
        if self.error:
            d["error"] = self.error
        return d


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
