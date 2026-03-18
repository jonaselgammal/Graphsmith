"""Tests for Sprint 25: planner scaling — retrieval, scoring, stop words, synonyms."""
from __future__ import annotations

from pathlib import Path

import pytest

from graphsmith.planner.candidates import (
    _relevance_score, _tokenise, _STOP_WORDS, _SYNONYMS,
    retrieve_candidates,
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


class TestTokenise:
    def test_filters_stop_words(self) -> None:
        tokens = _tokenise("this text from the data")
        assert "this" not in tokens
        assert "text" not in tokens
        assert "from" not in tokens

    def test_expands_synonyms(self) -> None:
        tokens = _tokenise("clean the text")
        assert "clean" in tokens
        assert "normalize" in tokens  # synonym expansion

    def test_capitalize_synonym(self) -> None:
        tokens = _tokenise("capitalize words")
        assert "title" in tokens or "case" in tokens

    def test_count_synonym(self) -> None:
        tokens = _tokenise("count the words")
        assert "word" in tokens

    def test_no_duplicates(self) -> None:
        tokens = _tokenise("normalize normalize normalize")
        assert tokens.count("normalize") == 1


class TestRelevanceScore:
    def test_tag_match_scores_higher(self) -> None:
        entry = IndexEntry(
            id="test.v1", name="Test", version="1.0.0",
            description="A test skill",
            tags=["keywords", "extraction"],
        )
        score = _relevance_score(entry, ["keywords"])
        assert score >= 2  # tag match

    def test_description_match(self) -> None:
        entry = IndexEntry(
            id="test.v1", name="Test", version="1.0.0",
            description="Count the number of words",
        )
        score = _relevance_score(entry, ["words", "count"])
        assert score >= 2

    def test_no_substring_false_positive(self) -> None:
        entry = IndexEntry(
            id="test.v1", name="Reverse", version="1.0.0",
            description="Rarely needed for most tasks",
        )
        score = _relevance_score(entry, ["are"])
        assert score == 0  # "are" is not a word in the metadata


class TestRetrieveCandidates:
    def test_word_count_goal(self, full_reg: LocalRegistry) -> None:
        cands = retrieve_candidates("How many words are in this text", full_reg)
        ids = {c.id for c in cands}
        assert "text.word_count.v1" in ids
        assert len(cands) <= 8

    def test_no_distractors_for_sentiment(self, full_reg: LocalRegistry) -> None:
        cands = retrieve_candidates("Tell me the sentiment", full_reg)
        ids = {c.id for c in cands}
        assert "text.classify_sentiment.v1" in ids
        assert "text.reverse.v1" not in ids
        assert "text.sort_lines.v1" not in ids

    def test_clean_includes_normalize(self, full_reg: LocalRegistry) -> None:
        cands = retrieve_candidates("Clean this text", full_reg)
        ids = {c.id for c in cands}
        assert "text.normalize.v1" in ids

    def test_max_candidates_respected(self, full_reg: LocalRegistry) -> None:
        cands = retrieve_candidates("anything", full_reg, max_candidates=3)
        assert len(cands) <= 3

    def test_fallback_returns_some_skills(self, full_reg: LocalRegistry) -> None:
        cands = retrieve_candidates("xyzzy zork gibberish", full_reg)
        assert len(cands) > 0


class TestScriptsExist:
    @pytest.mark.parametrize("script", [
        "eval_benchmark.sh", "eval_holdout.sh",
        "eval_challenge.sh", "eval_all.sh",
    ])
    def test_script_exists(self, script: str) -> None:
        assert (SCRIPTS_DIR / script).exists()

    @pytest.mark.parametrize("script", [
        "eval_benchmark.sh", "eval_holdout.sh",
        "eval_challenge.sh", "eval_all.sh",
    ])
    def test_script_is_executable(self, script: str) -> None:
        import os
        assert os.access(SCRIPTS_DIR / script, os.X_OK)

    def test_eval_all_references_three_sets(self) -> None:
        content = (SCRIPTS_DIR / "eval_all.sh").read_text()
        assert "evaluation/goals" in content
        assert "evaluation/holdout_goals" in content
        assert "evaluation/challenge_goals" in content
