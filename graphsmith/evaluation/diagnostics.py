"""Diagnostics helpers for planner evaluation results."""
from __future__ import annotations

from typing import Any


def infer_failure_type(result: dict[str, Any]) -> str:
    """Infer failure type from evaluation result content.

    Returns "provider", "retrieval", or "planner".
    """
    error = (result.get("error") or "").lower()
    holes_text = " ".join(result.get("holes", [])).lower()

    provider_signals = [
        "429", "rate limit", "provider error", "credit balance",
        "api key", "authentication", "unauthorized", "forbidden",
        "api error", "provider call failed", "connect", "timeout",
    ]
    if any(s in error or s in holes_text for s in provider_signals):
        return "provider"
    if result.get("expected_in_shortlist") is False:
        return "retrieval"
    return "planner"
