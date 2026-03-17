"""Promotion candidate prototype — mine repeated op-sequence patterns from traces."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

from graphsmith.traces.store import TraceStore


class PromotionCandidate(BaseModel):
    """A repeated fragment that may be worth promoting to a reusable skill."""

    signature: str
    ops: list[str]
    frequency: int
    trace_ids: list[str]
    inferred_inputs: list[str] = Field(default_factory=list)
    inferred_outputs: list[str] = Field(default_factory=list)
    notes: str = (
        "v1 heuristic: op-sequence match only. "
        "Does not compare config, edges, or nested structure."
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
    # signature -> list of (trace_id, trace_dict)
    groups: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)

    for trace_id in store.list_ids():
        trace = store.load(trace_id)
        sig = _extract_signature(trace)
        if sig:
            groups[sig].append((trace_id, trace))

    candidates: list[PromotionCandidate] = []
    for sig, entries in sorted(groups.items()):
        if len(entries) < min_frequency:
            continue

        ops = sig.split(" -> ")
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
            ops=ops,
            frequency=len(entries),
            trace_ids=trace_ids,
            inferred_inputs=sorted(all_inputs),
            inferred_outputs=sorted(all_outputs),
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
