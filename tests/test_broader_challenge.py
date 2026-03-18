"""Tests for Sprint 23: broader challenge set — new skills, distractors, challenge goals."""
from __future__ import annotations

from pathlib import Path

import pytest

from graphsmith.evaluation.planner_eval import load_goals, run_evaluation
from graphsmith.ops.text_ops import (
    text_word_count, text_reverse, text_sort_lines,
    text_remove_duplicates, text_title_case,
)
from graphsmith.parser import load_skill_package
from graphsmith.planner import MockPlannerBackend
from graphsmith.registry import LocalRegistry
from graphsmith.runtime import run_skill_package
from graphsmith.validator import validate_skill_package

from conftest import EXAMPLE_DIR

CHALLENGE_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "challenge_goals"
GOALS_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "goals"
HOLDOUT_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "holdout_goals"

NEW_SKILLS = [
    "text.word_count.v1", "text.title_case.v1", "text.classify_sentiment.v1",
    "json.extract_field.v1", "text.prefix_lines.v1",
    "text.reverse.v1", "text.sort_lines.v1", "text.remove_duplicates.v1",
    "json.pretty_print.v1",
]


@pytest.fixture()
def full_reg(tmp_path: Path) -> LocalRegistry:
    r = LocalRegistry(root=tmp_path / "reg")
    for skill_dir in sorted((EXAMPLE_DIR).iterdir()):
        if skill_dir.is_dir():
            r.publish(skill_dir)
    return r


# ── new skill validation ─────────────────────────────────────────────


class TestNewSkillsValidate:
    @pytest.mark.parametrize("skill", NEW_SKILLS)
    def test_validates(self, skill: str) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / skill)
        validate_skill_package(pkg)


# ── new skill execution ──────────────────────────────────────────────


class TestNewSkillExecution:
    def test_word_count(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.word_count.v1")
        result = run_skill_package(pkg, {"text": "one two three"})
        assert result.outputs["count"] == "3"

    def test_title_case(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.title_case.v1")
        result = run_skill_package(pkg, {"text": "hello world"})
        assert result.outputs["titled"] == "Hello World"

    def test_reverse(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.reverse.v1")
        result = run_skill_package(pkg, {"text": "abc"})
        assert result.outputs["reversed"] == "cba"

    def test_sort_lines(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.sort_lines.v1")
        result = run_skill_package(pkg, {"text": "c\na\nb"})
        assert result.outputs["sorted"] == "a\nb\nc"

    def test_remove_duplicates(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.remove_duplicates.v1")
        result = run_skill_package(pkg, {"text": "a\nb\na"})
        assert result.outputs["deduplicated"] == "a\nb"

    def test_prefix_lines(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.prefix_lines.v1")
        result = run_skill_package(pkg, {"text": "hello", "prefix": "Header:"})
        assert result.outputs["prefixed"] == "Header:\nhello"


# ── op unit tests ────────────────────────────────────────────────────


class TestNewOps:
    def test_word_count_op(self) -> None:
        assert text_word_count({}, {"text": "a b c"}) == {"count": "3"}

    def test_word_count_empty(self) -> None:
        assert text_word_count({}, {"text": ""}) == {"count": "0"}

    def test_reverse_op(self) -> None:
        assert text_reverse({}, {"text": "hello"}) == {"reversed": "olleh"}

    def test_sort_lines_op(self) -> None:
        assert text_sort_lines({}, {"text": "b\na"}) == {"sorted": "a\nb"}

    def test_remove_duplicates_op(self) -> None:
        assert text_remove_duplicates({}, {"text": "x\ny\nx"}) == {"deduplicated": "x\ny"}

    def test_title_case_op(self) -> None:
        assert text_title_case({}, {"text": "hello world"}) == {"titled": "Hello World"}


# ── challenge goals ──────────────────────────────────────────────────


class TestChallengeGoals:
    def test_loads_12_goals(self) -> None:
        goals = load_goals(CHALLENGE_DIR)
        assert len(goals) == 12

    def test_no_overlap_with_benchmark(self) -> None:
        bench = {g.goal for g in load_goals(GOALS_DIR)}
        challenge = {g.goal for g in load_goals(CHALLENGE_DIR)}
        assert bench & challenge == set()

    def test_no_overlap_with_holdout(self) -> None:
        holdout = {g.goal for g in load_goals(HOLDOUT_DIR)}
        challenge = {g.goal for g in load_goals(CHALLENGE_DIR)}
        assert holdout & challenge == set()

    def test_runs_with_mock(self, full_reg: LocalRegistry) -> None:
        goals = load_goals(CHALLENGE_DIR)
        report = run_evaluation(goals, full_reg, MockPlannerBackend())
        assert report.goals_total == 12

    def test_uses_new_skills(self) -> None:
        goals = load_goals(CHALLENGE_DIR)
        all_skills = set()
        for g in goals:
            all_skills.update(g.expected_skills)
        assert "text.word_count.v1" in all_skills
        assert "text.title_case.v1" in all_skills
        assert "text.classify_sentiment.v1" in all_skills


# ── full registry has all skills ─────────────────────────────────────


class TestFullRegistry:
    def test_has_15_skills(self, full_reg: LocalRegistry) -> None:
        entries = full_reg.list_all()
        assert len(entries) >= 15

    def test_has_distractor_skills(self, full_reg: LocalRegistry) -> None:
        ids = {e.id for e in full_reg.list_all()}
        assert "text.reverse.v1" in ids
        assert "text.sort_lines.v1" in ids
        assert "text.remove_duplicates.v1" in ids
        assert "json.pretty_print.v1" in ids
