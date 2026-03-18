"""Candidate skill retrieval from the local registry."""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from graphsmith.registry.index import IndexEntry
from graphsmith.registry.local import LocalRegistry

_DEFAULT_MAX = 8

_STOP_WORDS = {
    "this", "that", "the", "from", "with", "and", "then", "also",
    "text", "data", "them", "into", "for", "its", "give", "get",
    "make", "take", "both", "all", "want", "just", "here",
}

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

RETRIEVAL_MODES = ("ranked", "broad", "ranked_broad")


class RetrievalDiagnostics(BaseModel):
    """Diagnostic info for one retrieval call."""

    goal: str = ""
    mode: str = "ranked"
    raw_tokens: list[str] = Field(default_factory=list)
    expanded_tokens: list[str] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)
    scores: dict[str, int] = Field(default_factory=dict)
    candidate_count: int = 0


def retrieve_candidates(
    goal: str,
    registry: LocalRegistry,
    *,
    max_candidates: int = _DEFAULT_MAX,
    mode: str = "ranked",
) -> list[IndexEntry]:
    """Retrieve candidate skills, ranked by relevance."""
    _, entries = retrieve_candidates_with_diagnostics(
        goal, registry, max_candidates=max_candidates, mode=mode,
    )
    return entries


def retrieve_candidates_with_diagnostics(
    goal: str,
    registry: LocalRegistry,
    *,
    max_candidates: int = _DEFAULT_MAX,
    mode: str = "ranked",
) -> tuple[RetrievalDiagnostics, list[IndexEntry]]:
    """Retrieve candidates and return diagnostics alongside."""
    if mode == "broad":
        return _retrieve_broad(goal, registry, max_candidates=max(max_candidates, 15))
    elif mode == "ranked_broad":
        return _retrieve_ranked(goal, registry, max_candidates=12)
    else:
        return _retrieve_ranked(goal, registry, max_candidates=max_candidates)


def _retrieve_ranked(
    goal: str,
    registry: LocalRegistry,
    *,
    max_candidates: int = _DEFAULT_MAX,
) -> tuple[RetrievalDiagnostics, list[IndexEntry]]:
    """Ranked retrieval: stop words + synonyms + word-boundary scoring."""
    raw_tokens = _tokenise_raw(goal)
    tokens = _expand_synonyms(raw_tokens)
    all_entries = registry.list_all()

    diag = RetrievalDiagnostics(
        goal=goal, mode="ranked",
        raw_tokens=raw_tokens, expanded_tokens=tokens,
    )

    if not tokens or not all_entries:
        diag.candidates = [e.id for e in all_entries[:max_candidates]]
        diag.candidate_count = len(diag.candidates)
        return diag, all_entries[:max_candidates]

    scored: list[tuple[int, IndexEntry]] = []
    for entry in all_entries:
        score = _relevance_score(entry, tokens)
        scored.append((score, entry))
        diag.scores[entry.id] = score

    scored.sort(key=lambda x: (-x[0], x[1].id, x[1].version))
    results = [entry for score, entry in scored if score > 0]
    if not results:
        results = all_entries
    results = results[:max_candidates]

    diag.candidates = [e.id for e in results]
    diag.candidate_count = len(results)
    return diag, results


def _retrieve_broad(
    goal: str,
    registry: LocalRegistry,
    *,
    max_candidates: int = 15,
) -> tuple[RetrievalDiagnostics, list[IndexEntry]]:
    """Broad retrieval: no stop words, no synonyms, substring matching."""
    raw_tokens = _tokenise_no_filter(goal)

    diag = RetrievalDiagnostics(
        goal=goal, mode="broad",
        raw_tokens=raw_tokens, expanded_tokens=raw_tokens,
    )

    all_entries = registry.list_all()
    seen: dict[tuple[str, str], IndexEntry] = {}

    for token in raw_tokens:
        for entry in registry.search(token):
            key = (entry.id, entry.version)
            if key not in seen:
                seen[key] = entry

    if not seen:
        results = all_entries
    else:
        results = sorted(seen.values(), key=lambda e: (e.id, e.version))

    results = results[:max_candidates]
    diag.candidates = [e.id for e in results]
    diag.candidate_count = len(results)
    return diag, results


# ── scoring helpers ──────────────────────────────────────────────────


def _relevance_score(entry: IndexEntry, tokens: list[str]) -> int:
    id_words = set(re.findall(r"[a-z0-9]+", entry.id.lower()))
    name_words = set(re.findall(r"[a-z0-9]+", entry.name.lower()))
    desc_words = set(re.findall(r"[a-z0-9]+", entry.description.lower()))
    tag_words: set[str] = set()
    for t in entry.tags:
        tag_words.update(re.findall(r"[a-z0-9]+", t.lower()))
    all_words = id_words | name_words | desc_words | tag_words

    score = 0
    for token in tokens:
        if token in tag_words:
            score += 2
        elif token in all_words:
            score += 1
    return score


def _tokenise_raw(text: str) -> list[str]:
    """Tokenise with stop words filtered, no synonym expansion."""
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        if len(w) >= 3 and w not in seen and w not in _STOP_WORDS:
            seen.add(w)
            out.append(w)
    return out


def _expand_synonyms(tokens: list[str]) -> list[str]:
    """Expand tokens with synonym mappings."""
    seen = set(tokens)
    out = list(tokens)
    for t in list(tokens):
        for syn in _SYNONYMS.get(t, []):
            if syn not in seen:
                seen.add(syn)
                out.append(syn)
    return out


def _tokenise_no_filter(text: str) -> list[str]:
    """Tokenise without stop words or synonyms (broad mode)."""
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        if len(w) >= 3 and w not in seen:
            seen.add(w)
            out.append(w)
    return out


# Backward compat alias
def _tokenise(text: str) -> list[str]:
    return _expand_synonyms(_tokenise_raw(text))
