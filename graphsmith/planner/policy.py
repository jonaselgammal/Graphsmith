"""Planner-visible policy extraction and candidate filtering."""
from __future__ import annotations

from graphsmith.registry.index import IndexEntry

_TRUSTED_THRESHOLD = 0.7


def derive_goal_constraints(goal: str) -> list[str]:
    """Extract explicit policy constraints from the natural-language goal."""
    goal_lower = goal.lower()
    constraints: list[str] = []
    if _requires_published_only(goal_lower):
        constraints.append("Use only already published skills; do not generate new skills.")
    if _requires_trusted_published_only(goal_lower):
        constraints.append(
            f"Use only trusted published skills with trust_score >= {_TRUSTED_THRESHOLD:.1f}; "
            "do not generate new skills."
        )
    return constraints


def requires_published_only(goal: str) -> bool:
    return _requires_published_only(goal.lower())


def requires_trusted_published_only(goal: str) -> bool:
    return _requires_trusted_published_only(goal.lower())


def is_published_entry(entry: IndexEntry) -> bool:
    return _entry_is_published(entry)


def is_trusted_published_entry(entry: IndexEntry) -> bool:
    return _entry_is_trusted_published(entry)


def filter_candidates_by_goal_policy(
    entries: list[IndexEntry],
    goal: str,
) -> list[IndexEntry]:
    """Filter candidates according to explicit goal policy."""
    goal_lower = goal.lower()
    if _requires_trusted_published_only(goal_lower):
        return [
            entry for entry in entries
            if _entry_is_trusted_published(entry)
        ]
    if _requires_published_only(goal_lower):
        return [
            entry for entry in entries
            if _entry_is_published(entry)
        ]
    return entries


def _requires_published_only(goal_lower: str) -> bool:
    return (
        "published skill" in goal_lower
        or "published skills" in goal_lower
        or "already published" in goal_lower
    )


def _requires_trusted_published_only(goal_lower: str) -> bool:
    return (
        "trusted published skill" in goal_lower
        or "trusted published skills" in goal_lower
        or "only trusted" in goal_lower
    )


def _entry_is_published(entry: IndexEntry) -> bool:
    return bool(entry.published_at)


def _entry_is_trusted_published(entry: IndexEntry) -> bool:
    if not _entry_is_published(entry):
        return False
    trust = entry.trust_score
    return trust is not None and trust >= _TRUSTED_THRESHOLD
