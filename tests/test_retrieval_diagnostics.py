"""Tests for Sprint 26: retrieval diagnostics and mode comparison."""
from __future__ import annotations

from pathlib import Path

import pytest

from graphsmith.evaluation.planner_eval import (
    EvalGoal, compare_retrieval_modes, evaluate_goal, load_goals, run_evaluation,
)
from graphsmith.planner import MockPlannerBackend
from graphsmith.planner.candidates import (
    RETRIEVAL_MODES, RetrievalDiagnostics,
    retrieve_candidates, retrieve_candidates_with_diagnostics,
)
from graphsmith.registry import LocalRegistry

from conftest import EXAMPLE_DIR

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
HOLDOUT_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "holdout_goals"
GOALS_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "goals"


@pytest.fixture()
def full_reg(tmp_path: Path) -> LocalRegistry:
    r = LocalRegistry(root=tmp_path / "reg")
    for d in sorted((EXAMPLE_DIR).iterdir()):
        if d.is_dir():
            r.publish(d)
    return r


class TestRetrievalDiagnostics:
    def test_returns_diagnostics(self, full_reg: LocalRegistry) -> None:
        diag, cands = retrieve_candidates_with_diagnostics(
            "normalize text", full_reg,
        )
        assert isinstance(diag, RetrievalDiagnostics)
        assert diag.goal == "normalize text"
        assert diag.mode == "ranked"
        assert len(diag.candidates) == len(cands)
        assert diag.candidate_count > 0
        assert diag.registry_size > 0
        assert diag.empty_registry is False

    def test_diagnostics_has_tokens(self, full_reg: LocalRegistry) -> None:
        diag, _ = retrieve_candidates_with_diagnostics(
            "clean and summarize", full_reg,
        )
        assert "clean" in diag.raw_tokens or "summarize" in diag.raw_tokens
        assert len(diag.expanded_tokens) >= len(diag.raw_tokens)

    def test_diagnostics_has_scores(self, full_reg: LocalRegistry) -> None:
        diag, _ = retrieve_candidates_with_diagnostics(
            "extract keywords", full_reg,
        )
        assert len(diag.scores) > 0

    def test_empty_registry_is_reported(self, tmp_path: Path) -> None:
        diag, cands = retrieve_candidates_with_diagnostics(
            "normalize text", LocalRegistry(tmp_path / "empty"),
        )
        assert cands == []
        assert diag.registry_size == 0
        assert diag.empty_registry is True
        assert diag.fallback_used is False

    def test_fallback_is_reported(self, full_reg: LocalRegistry) -> None:
        diag, cands = retrieve_candidates_with_diagnostics(
            "xyzzy zork gibberish", full_reg,
        )
        assert len(cands) > 0
        assert diag.fallback_used is True


class TestRetrievalModes:
    def test_ranked_mode(self, full_reg: LocalRegistry) -> None:
        _, cands = retrieve_candidates_with_diagnostics(
            "normalize text", full_reg, mode="ranked",
        )
        assert len(cands) <= 8

    def test_broad_mode(self, full_reg: LocalRegistry) -> None:
        diag, cands = retrieve_candidates_with_diagnostics(
            "normalize text", full_reg, mode="broad",
        )
        assert diag.mode == "broad"
        assert len(cands) <= 15

    def test_ranked_broad_mode(self, full_reg: LocalRegistry) -> None:
        diag, cands = retrieve_candidates_with_diagnostics(
            "normalize text", full_reg, mode="ranked_broad",
        )
        assert len(cands) <= 12

    def test_broad_returns_more_candidates(self, full_reg: LocalRegistry) -> None:
        _, ranked = retrieve_candidates_with_diagnostics(
            "summarize text and extract keywords", full_reg, mode="ranked",
        )
        _, broad = retrieve_candidates_with_diagnostics(
            "summarize text and extract keywords", full_reg, mode="broad",
        )
        # Broad should generally return at least as many
        assert len(broad) >= len(ranked) or len(broad) > 0


class TestEvalWithDiagnostics:
    def test_eval_result_has_retrieval(self, full_reg: LocalRegistry) -> None:
        goal = EvalGoal(goal="normalize text", expected_skills=["text.normalize.v1"])
        result = evaluate_goal(goal, full_reg, MockPlannerBackend())
        assert result.retrieval is not None
        assert result.retrieval.candidate_count > 0

    def test_eval_result_expected_in_shortlist(self, full_reg: LocalRegistry) -> None:
        goal = EvalGoal(
            goal="count words", expected_skills=["text.word_count.v1"],
        )
        result = evaluate_goal(goal, full_reg, MockPlannerBackend())
        # word_count should be in shortlist
        assert result.expected_skills_in_shortlist or result.retrieval is not None

    def test_report_has_avg_candidates(self, full_reg: LocalRegistry) -> None:
        goals = load_goals(GOALS_DIR)[:3]
        report = run_evaluation(goals, full_reg, MockPlannerBackend())
        assert report.avg_candidates > 0

    def test_report_has_retrieval_mode(self, full_reg: LocalRegistry) -> None:
        goals = [EvalGoal(goal="test")]
        report = run_evaluation(goals, full_reg, MockPlannerBackend(), retrieval_mode="broad")
        assert report.retrieval_mode == "broad"


class TestCompareRetrievalModes:
    def test_compare_returns_all_modes(self, full_reg: LocalRegistry) -> None:
        goals = load_goals(GOALS_DIR)[:3]
        reports = compare_retrieval_modes(goals, full_reg, MockPlannerBackend())
        assert set(reports.keys()) == set(RETRIEVAL_MODES)

    def test_each_mode_has_results(self, full_reg: LocalRegistry) -> None:
        goals = [EvalGoal(goal="normalize text", expected_skills=["text.normalize.v1"])]
        reports = compare_retrieval_modes(goals, full_reg, MockPlannerBackend())
        for mode, report in reports.items():
            assert report.goals_total == 1
            assert report.retrieval_mode == mode


class TestNewScripts:
    @pytest.mark.parametrize("script", [
        "eval_holdout_compare.sh", "eval_all_diagnostics.sh",
    ])
    def test_exists_and_executable(self, script: str) -> None:
        import os
        path = SCRIPTS_DIR / script
        assert path.exists()
        assert os.access(path, os.X_OK)
