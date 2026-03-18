"""Diagnostics helpers for planner evaluation results."""
from __future__ import annotations

from typing import Any


def infer_failure_type(result: dict[str, Any]) -> str:
    """Infer failure type from evaluation result content.

    Returns "provider", "retrieval", or "planner".
    """
    error = (result.get("error") or "").lower()
    holes_text = " ".join(result.get("holes", [])).lower()

    if any(s in error or s in holes_text for s in ["429", "rate limit", "provider error"]):
        return "provider"
    if result.get("expected_in_shortlist") is False:
        return "retrieval"
    return "planner"
