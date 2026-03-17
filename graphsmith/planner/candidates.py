"""Candidate skill retrieval from the local registry."""
from __future__ import annotations

import re

from graphsmith.registry.index import IndexEntry
from graphsmith.registry.local import LocalRegistry

_DEFAULT_MAX = 20


def retrieve_candidates(
    goal: str,
    registry: LocalRegistry,
    *,
    max_candidates: int = _DEFAULT_MAX,
) -> list[IndexEntry]:
    """Retrieve candidate skills for a planning goal.

    Strategy (deterministic, no embeddings):
    1. Tokenise the goal into lowercase alpha-numeric words.
    2. For each token, run registry.search(token).
    3. Deduplicate by (id, version).
    4. Sort by (id, version).
    5. Truncate to max_candidates.
    """
    tokens = _tokenise(goal)
    seen: dict[tuple[str, str], IndexEntry] = {}

    for token in tokens:
        for entry in registry.search(token):
            key = (entry.id, entry.version)
            if key not in seen:
                seen[key] = entry

    # Also include all skills if the goal is generic (no token hits)
    if not seen:
        for entry in registry.list_all():
            key = (entry.id, entry.version)
            seen[key] = entry

    results = sorted(seen.values(), key=lambda e: (e.id, e.version))
    return results[:max_candidates]


def _tokenise(text: str) -> list[str]:
    """Split text into unique lowercase tokens (3+ chars)."""
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        if len(w) >= 3 and w not in seen:
            seen.add(w)
            out.append(w)
    return out
