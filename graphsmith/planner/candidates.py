"""Candidate skill retrieval from the local registry."""
from __future__ import annotations

import re

from graphsmith.registry.index import IndexEntry
from graphsmith.registry.local import LocalRegistry

_DEFAULT_MAX = 8

# Common words that match too many skills and don't discriminate
_STOP_WORDS = {
    "this", "that", "the", "from", "with", "and", "then", "also",
    "text", "data", "them", "into", "for", "its", "give", "get",
    "make", "take", "both", "all", "want", "just", "here",
}

# Map common goal-language synonyms to skill-metadata words
_SYNONYMS: dict[str, list[str]] = {
    "clean": ["normalize", "cleanup"],
    "tidy": ["normalize", "cleanup"],
    "topics": ["keywords", "extract"],
    "find": ["extract"],
    "condense": ["summarize", "summary"],
    "brief": ["summarize", "summary"],
    "capitalize": ["title", "case"],
    "count": ["word", "count"],
    "many": ["count", "word"],
    "parse": ["json", "extract"],
    "header": ["prefix", "format"],
    "bullet": ["join", "format", "list"],
    "list": ["join", "format"],
    "sentiment": ["sentiment", "classify"],
    "feeling": ["sentiment", "classify"],
}


def retrieve_candidates(
    goal: str,
    registry: LocalRegistry,
    *,
    max_candidates: int = _DEFAULT_MAX,
) -> list[IndexEntry]:
    """Retrieve candidate skills for a planning goal, ranked by relevance.

    Strategy (deterministic, no embeddings):
    1. Tokenise the goal into discriminating tokens (skip stop words).
    2. Score each skill by how many tokens match its metadata.
    3. Sort by score descending, then by (id, version) for determinism.
    4. Return top max_candidates.
    """
    tokens = _tokenise(goal)
    all_entries = registry.list_all()

    if not tokens or not all_entries:
        return all_entries[:max_candidates]

    scored: list[tuple[int, IndexEntry]] = []
    for entry in all_entries:
        score = _relevance_score(entry, tokens)
        scored.append((score, entry))

    # Sort: highest score first, then alphabetical for ties
    scored.sort(key=lambda x: (-x[0], x[1].id, x[1].version))

    # Only include skills with score > 0, up to max_candidates
    results = [entry for score, entry in scored if score > 0]
    if not results:
        # Fallback: return all skills if nothing matched
        results = all_entries

    return results[:max_candidates]


def _relevance_score(entry: IndexEntry, tokens: list[str]) -> int:
    """Score a skill by how many goal tokens match its metadata.

    Uses word-boundary matching to avoid substring false positives
    (e.g. "are" matching "Rarely"). Tag matches score higher.
    """
    # Build word sets from metadata
    id_words = set(re.findall(r"[a-z0-9]+", entry.id.lower()))
    name_words = set(re.findall(r"[a-z0-9]+", entry.name.lower()))
    desc_words = set(re.findall(r"[a-z0-9]+", entry.description.lower()))
    tag_words = set()
    for t in entry.tags:
        tag_words.update(re.findall(r"[a-z0-9]+", t.lower()))

    all_words = id_words | name_words | desc_words | tag_words

    score = 0
    for token in tokens:
        if token in tag_words:
            score += 2  # tag match is stronger signal
        elif token in all_words:
            score += 1
    return score


def _tokenise(text: str) -> list[str]:
    """Split text into unique discriminating tokens, expanded with synonyms."""
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        if len(w) >= 3 and w not in seen and w not in _STOP_WORDS:
            seen.add(w)
            out.append(w)
            # Expand synonyms
            for syn in _SYNONYMS.get(w, []):
                if syn not in seen:
                    seen.add(syn)
                    out.append(syn)
    return out
