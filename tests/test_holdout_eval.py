"""Tests for Sprint 20: holdout evaluation set and benchmark separation."""
from __future__ import annotations

from pathlib import Path

import pytest

from graphsmith.evaluation.planner_eval import load_goals, run_evaluation
from graphsmith.planner import MockPlannerBackend
from graphsmith.registry import LocalRegistry

from conftest import EXAMPLE_DIR

GOALS_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "goals"
HOLDOUT_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "holdout_goals"


@pytest.fixture()
def reg(tmp_path: Path) -> LocalRegistry:
    r = LocalRegistry(root=tmp_path / "reg")
    for skill in ["text.normalize.v1", "text.extract_keywords.v1",
                   "text.summarize.v1", "json.reshape.v1", "text.join_lines.v1"]:
        r.publish(EXAMPLE_DIR / skill)
    return r


class TestBenchmarkV1:
    def test_loads_9_goals(self) -> None:
        goals = load_goals(GOALS_DIR)
        assert len(goals) == 9

    def test_all_goals_have_expected_skills(self) -> None:
        goals = load_goals(GOALS_DIR)
        for g in goals:
            assert g.goal
            assert g.min_nodes >= 1

    def test_runs_with_mock(self, reg: LocalRegistry) -> None:
        goals = load_goals(GOALS_DIR)
        report = run_evaluation(goals, reg, MockPlannerBackend())
        assert report.goals_total == 9


class TestHoldoutSet:
    def test_loads_15_goals(self) -> None:
        goals = load_goals(HOLDOUT_DIR)
        assert len(goals) == 15

    def test_all_goals_have_required_fields(self) -> None:
        goals = load_goals(HOLDOUT_DIR)
        for g in goals:
            assert g.goal
            assert g.min_nodes >= 1
            assert g.expected_skills  # every holdout goal should name expected skills

    def test_no_overlap_with_benchmark(self) -> None:
        bench = {g.goal for g in load_goals(GOALS_DIR)}
        holdout = {g.goal for g in load_goals(HOLDOUT_DIR)}
        overlap = bench & holdout
        assert overlap == set(), f"Overlapping goals: {overlap}"

    def test_runs_with_mock(self, reg: LocalRegistry) -> None:
        goals = load_goals(HOLDOUT_DIR)
        report = run_evaluation(goals, reg, MockPlannerBackend())
        assert report.goals_total == 15

    def test_uses_variety_of_skills(self) -> None:
        goals = load_goals(HOLDOUT_DIR)
        all_skills = set()
        for g in goals:
            all_skills.update(g.expected_skills)
        # Should reference at least 4 different skills
        assert len(all_skills) >= 4

    def test_includes_multi_node_goals(self) -> None:
        goals = load_goals(HOLDOUT_DIR)
        multi = [g for g in goals if g.min_nodes >= 2]
        assert len(multi) >= 5

    def test_includes_three_node_goals(self) -> None:
        goals = load_goals(HOLDOUT_DIR)
        three = [g for g in goals if g.min_nodes >= 3]
        assert len(three) >= 3


class TestBothSetsRunnable:
    def test_benchmark_then_holdout(self, reg: LocalRegistry) -> None:
        bench = run_evaluation(load_goals(GOALS_DIR), reg, MockPlannerBackend())
        holdout = run_evaluation(load_goals(HOLDOUT_DIR), reg, MockPlannerBackend())
        assert bench.goals_total == 9
        assert holdout.goals_total == 15
        # Both should complete without errors
        for r in bench.results + holdout.results:
            assert r.status in ("pass", "partial", "fail")
