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
    "summary": ["summarize", "summarization"],
    "summarize": ["summary", "summarization"],
    "write": ["summarize", "generate"],
    "capitalize": ["title", "case"],
    "count": ["word", "count"],
    "many": ["count", "word"],
    "words": ["word", "count"],
    "parse": ["json", "extract"],
    "header": ["prefix", "format"],
    "bullet": ["join", "format", "list"],
    "list": ["join", "format"],
    "sentiment": ["sentiment", "classify"],
    "feeling": ["sentiment", "classify"],
    "analyze": ["classify", "sentiment", "analysis"],
    "short": ["summarize", "summary"],
}

# Common suffixes stripped during stem matching
_SUFFIX_PATTERNS = re.compile(
    r"(ization|isation|ments?|ness|tion|sion|ize|ise|ing|ous|ful|ble|ity|ed|er|ly|es|al|s)$"
)

RETRIEVAL_MODES = ("ranked", "ranked_recall", "broad", "ranked_broad")


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
        return _retrieve_ranked(goal, registry, max_candidates=12, use_stems=False, mode_name="ranked_broad")
    elif mode == "ranked_recall":
        return _retrieve_ranked(goal, registry, max_candidates=10, use_stems=True, mode_name="ranked_recall")
    else:
        return _retrieve_ranked(goal, registry, max_candidates=max_candidates, use_stems=False, mode_name="ranked")


def _retrieve_ranked(
    goal: str,
    registry: LocalRegistry,
    *,
    max_candidates: int = _DEFAULT_MAX,
    use_stems: bool = False,
    mode_name: str = "ranked",
) -> tuple[RetrievalDiagnostics, list[IndexEntry]]:
    """Ranked retrieval with optional stem matching."""
    raw_tokens = _tokenise_raw(goal)
    tokens = _expand_synonyms(raw_tokens)
    all_entries = registry.list_all()

    diag = RetrievalDiagnostics(
        goal=goal, mode=mode_name,
        raw_tokens=raw_tokens, expanded_tokens=tokens,
    )

    if not tokens or not all_entries:
        diag.candidates = [e.id for e in all_entries[:max_candidates]]
        diag.candidate_count = len(diag.candidates)
        return diag, all_entries[:max_candidates]

    scored: list[tuple[int, IndexEntry]] = []
    for entry in all_entries:
        score = _relevance_score(entry, tokens, use_stems=use_stems)
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


# ── scoring ──────────────────────────────────────────────────────────


def _stem(word: str) -> str:
    """Lightweight suffix stripping for matching word forms."""
    if len(word) <= 4:
        return word
    return _SUFFIX_PATTERNS.sub("", word) or word


def _relevance_score(
    entry: IndexEntry, tokens: list[str], *, use_stems: bool = False,
) -> int:
    """Score by token-to-metadata word overlap. Optionally stem-aware."""
    id_words = set(re.findall(r"[a-z0-9]+", entry.id.lower()))
    name_words = set(re.findall(r"[a-z0-9]+", entry.name.lower()))
    desc_words = set(re.findall(r"[a-z0-9]+", entry.description.lower()))
    tag_words: set[str] = set()
    for t in entry.tags:
        tag_words.update(re.findall(r"[a-z0-9]+", t.lower()))
    input_words: set[str] = set()
    output_words: set[str] = set()
    effect_words: set[str] = set()
    for name in (
        entry.input_names
        + entry.required_input_names
        + entry.optional_input_names
    ):
        input_words.update(re.findall(r"[a-z0-9]+", name.lower()))
    for name in entry.output_names:
        output_words.update(re.findall(r"[a-z0-9]+", name.lower()))
    for effect in entry.effects:
        effect_words.update(re.findall(r"[a-z0-9]+", effect.lower()))

    all_words = (
        id_words | name_words | desc_words | tag_words
        | input_words | output_words | effect_words
    )

    if use_stems:
        tag_stems = {_stem(w) for w in tag_words}
        input_stems = {_stem(w) for w in input_words}
        output_stems = {_stem(w) for w in output_words}
        effect_stems = {_stem(w) for w in effect_words}
        all_stems = {_stem(w) for w in all_words}
    else:
        tag_stems = tag_words
        input_stems = input_words
        output_stems = output_words
        effect_stems = effect_words
        all_stems = all_words

    score = 0
    for token in tokens:
        t = _stem(token) if use_stems else token
        if t in tag_stems:
            score += 3
        elif t in output_stems:
            score += 3
        elif t in input_stems:
            score += 2
        elif t in effect_stems:
            score += 2
        elif t in all_stems:
            score += 1
    return score


# ── tokenisation ─────────────────────────────────────────────────────


def _tokenise_raw(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        if len(w) >= 3 and w not in seen and w not in _STOP_WORDS:
            seen.add(w)
            out.append(w)
    return out


def _expand_synonyms(tokens: list[str]) -> list[str]:
    seen = set(tokens)
    out = list(tokens)
    for t in list(tokens):
        for syn in _SYNONYMS.get(t, []):
            if syn not in seen:
                seen.add(syn)
                out.append(syn)
    return out


def _tokenise_no_filter(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        if len(w) >= 3 and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _tokenise(text: str) -> list[str]:
    return _expand_synonyms(_tokenise_raw(text))
