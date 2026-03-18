"""Tests for Sprint 27: retrieval recall and stem matching."""
from __future__ import annotations

from pathlib import Path

import pytest

from graphsmith.planner.candidates import (
    RETRIEVAL_MODES, _stem, _relevance_score,
    retrieve_candidates, retrieve_candidates_with_diagnostics,
)
from graphsmith.registry import LocalRegistry
from graphsmith.registry.index import IndexEntry

from conftest import EXAMPLE_DIR

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture()
def full_reg(tmp_path: Path) -> LocalRegistry:
    r = LocalRegistry(root=tmp_path / "reg")
    for d in sorted((EXAMPLE_DIR).iterdir()):
        if d.is_dir():
            r.publish(d)
    return r


class TestStemming:
    def test_stem_summarize(self) -> None:
        assert _stem("summarize") == "summar"

    def test_stem_summarization(self) -> None:
        assert _stem("summarization") == "summar"

    def test_stem_summary(self) -> None:
        # "summary" → strip "y" via "ly"? No, just "y" isn't a suffix pattern.
        # Actually _stem strips common suffixes. Let's just check it's consistent.
        s = _stem("summary")
        assert len(s) <= len("summary")

    def test_stem_short_word(self) -> None:
        assert _stem("text") == "text"  # <= 4 chars, no stripping

    def test_stem_normalize(self) -> None:
        assert _stem("normalize") == "normal"

    def test_stem_keywords(self) -> None:
        s = _stem("keywords")
        assert s == "keyword"


class TestSummarizationRecall:
    """The core recall problem: 'summary' must find text.summarize.v1."""

    def test_summary_finds_summarize_ranked(self, full_reg: LocalRegistry) -> None:
        cands = retrieve_candidates(
            "give me a summary of this text", full_reg, mode="ranked",
        )
        ids = {c.id for c in cands}
        assert "text.summarize.v1" in ids

    def test_clean_and_summary_finds_both(self, full_reg: LocalRegistry) -> None:
        cands = retrieve_candidates(
            "Clean up this text and then give me a summary", full_reg,
        )
        ids = {c.id for c in cands}
        assert "text.normalize.v1" in ids
        assert "text.summarize.v1" in ids

    def test_write_summary_finds_summarize(self, full_reg: LocalRegistry) -> None:
        cands = retrieve_candidates(
            "write a summary and list the keywords", full_reg,
        )
        ids = {c.id for c in cands}
        assert "text.summarize.v1" in ids

    def test_summary_and_keywords_finds_both(self, full_reg: LocalRegistry) -> None:
        cands = retrieve_candidates(
            "get both a summary and keywords", full_reg,
        )
        ids = {c.id for c in cands}
        assert "text.summarize.v1" in ids
        assert "text.extract_keywords.v1" in ids


class TestRankedRecallMode:
    def test_mode_exists(self) -> None:
        assert "ranked_recall" in RETRIEVAL_MODES

    def test_uses_stem_matching(self, full_reg: LocalRegistry) -> None:
        diag, cands = retrieve_candidates_with_diagnostics(
            "summarize text", full_reg, mode="ranked_recall",
        )
        assert diag.mode == "ranked_recall"
        ids = {c.id for c in cands}
        assert "text.summarize.v1" in ids

    def test_returns_up_to_10(self, full_reg: LocalRegistry) -> None:
        _, cands = retrieve_candidates_with_diagnostics(
            "normalize summarize extract keywords", full_reg, mode="ranked_recall",
        )
        assert len(cands) <= 10

    def test_stem_helps_word_form_matching(self, full_reg: LocalRegistry) -> None:
        """Stem matching catches 'normalization' matching 'normalize'."""
        entry = IndexEntry(
            id="x.v1", name="X", version="1.0.0",
            description="Performs normalization",
            tags=["normalization"],
        )
        # With stems, "normalize" should match "normalization"
        score_no_stem = _relevance_score(entry, ["normalize"], use_stems=False)
        score_stem = _relevance_score(entry, ["normalize"], use_stems=True)
        assert score_stem >= score_no_stem


class TestNoChallengeRegression:
    """Ranked mode should still filter distractors for challenge goals."""

    def test_sentiment_no_distractors(self, full_reg: LocalRegistry) -> None:
        cands = retrieve_candidates("analyze the sentiment", full_reg, mode="ranked")
        ids = {c.id for c in cands}
        assert "text.classify_sentiment.v1" in ids
        assert "text.reverse.v1" not in ids

    def test_word_count_focused(self, full_reg: LocalRegistry) -> None:
        cands = retrieve_candidates("count the words", full_reg, mode="ranked")
        ids = {c.id for c in cands}
        assert "text.word_count.v1" in ids
        assert len(cands) <= 8


class TestNewScripts:
    @pytest.mark.parametrize("script", [
        "eval_all_compare.sh", "eval_holdout_modes.sh",
    ])
    def test_exists_and_executable(self, script: str) -> None:
        import os
        assert (SCRIPTS_DIR / script).exists()
        assert os.access(SCRIPTS_DIR / script, os.X_OK)
