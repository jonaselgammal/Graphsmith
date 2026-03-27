"""Promotion candidate prototype — mine repeated op-sequence patterns from traces."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

from graphsmith.traces.store import TraceStore


class PromotionCandidate(BaseModel):
    """A repeated fragment that may be worth promoting to a reusable skill."""

    signature: str
    structural_signature: str = ""
    ops: list[str]
    frequency: int
    trace_ids: list[str]
    inferred_inputs: list[str] = Field(default_factory=list)
    inferred_outputs: list[str] = Field(default_factory=list)
    suggested_skill_id: str = ""
    suggested_name: str = ""
    confidence: float = 0.0
    notes: str = (
        "v2 heuristic: groups by structural trace signature including nested child traces. "
        "Still does not compare full config values or exact graph edges."
    )


def find_promotion_candidates(
    store: TraceStore,
    *,
    min_frequency: int = 2,
) -> list[PromotionCandidate]:
    """Scan all traces and return promotion candidates.

    Heuristic: group traces by their top-level op-sequence signature.
    Any signature appearing >= min_frequency times becomes a candidate.
    """
    # structural signature -> list of (trace_id, trace_dict)
    groups: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)

    for trace_id in store.list_ids():
        trace = store.load(trace_id)
        sig = _extract_structural_signature(trace)
        if sig:
            groups[sig].append((trace_id, trace))

    candidates: list[PromotionCandidate] = []
    for structural_sig, entries in sorted(groups.items()):
        if len(entries) < min_frequency:
            continue

        sample_trace = entries[0][1]
        sig = _extract_signature(sample_trace)
        ops = sig.split(" -> ") if sig else []
        trace_ids = [tid for tid, _ in entries]

        # Gather union of input/output names across matching traces
        all_inputs: set[str] = set()
        all_outputs: set[str] = set()
        for _, trace in entries:
            for k in trace.get("inputs_summary", {}):
                all_inputs.add(k)
            for k in trace.get("outputs_summary", {}):
                all_outputs.add(k)

        candidates.append(PromotionCandidate(
            signature=sig,
            structural_signature=structural_sig,
            ops=ops,
            frequency=len(entries),
            trace_ids=trace_ids,
            inferred_inputs=sorted(all_inputs),
            inferred_outputs=sorted(all_outputs),
            suggested_skill_id=_suggest_skill_id(structural_sig, ops),
            suggested_name=_suggest_name(structural_sig, ops),
            confidence=_confidence_score(len(entries), structural_sig),
        ))

    # Sort by frequency descending, then signature for determinism
    candidates.sort(key=lambda c: (-c.frequency, c.signature))
    return candidates


def _extract_signature(trace: dict[str, Any]) -> str:
    """Extract the op-sequence signature from a trace dict.

    Returns a string like "template.render -> llm.generate".
    Returns "" if the trace has no nodes.
    """
    nodes = trace.get("nodes", [])
    if not nodes:
        return ""
    ops = [n.get("op", "?") for n in nodes]
    return " -> ".join(ops)


def _extract_structural_signature(trace: dict[str, Any]) -> str:
    """Extract a richer structural signature including nested child traces."""
    nodes = trace.get("nodes", [])
    if not nodes:
        return ""
    return " -> ".join(_node_structural_signature(node) for node in nodes)


def _node_structural_signature(node: dict[str, Any]) -> str:
    op = node.get("op", "?")
    child = node.get("child_trace")
    if not isinstance(child, dict):
        return op
    child_skill = child.get("skill_id", "")
    child_sig = _extract_signature(child)
    if child_skill:
        return f"{op}[{child_skill}]"
    if child_sig:
        return f"{op}{{{child_sig}}}"
    return op


def _slugify_parts(parts: list[str]) -> str:
    import re

    raw = "_then_".join(parts) if parts else "workflow"
    slug = re.sub(r"[^a-z0-9_]+", "_", raw.lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "workflow"


def _suggest_skill_id(structural_signature: str, ops: list[str]) -> str:
    parts: list[str] = []
    for segment in structural_signature.split(" -> "):
        if "[" in segment and "]" in segment:
            inner = segment.split("[", 1)[1].split("]", 1)[0]
            parts.append(inner.split(".v", 1)[0].split(".")[-1])
        else:
            parts.append(segment.split(".")[-1])
    slug = _slugify_parts(parts or ops)
    return f"promoted.{slug}.v1"


def _suggest_name(structural_signature: str, ops: list[str]) -> str:
    parts: list[str] = []
    for segment in structural_signature.split(" -> "):
        if "[" in segment and "]" in segment:
            inner = segment.split("[", 1)[1].split("]", 1)[0]
            parts.append(inner.split(".v", 1)[0].split(".")[-1].replace("_", " ").title())
        else:
            parts.append(segment.split(".")[-1].replace("_", " ").title())
    if not parts:
        parts = [op.replace("_", " ").title() for op in ops]
    return " Then ".join(parts) or "Promoted Workflow"


def _confidence_score(frequency: int, structural_signature: str) -> float:
    nested_bonus = 0.15 if "[" in structural_signature or "{" in structural_signature else 0.0
    freq_score = min(0.85, 0.3 + (frequency * 0.15))
    return round(min(0.99, freq_score + nested_bonus), 2)
