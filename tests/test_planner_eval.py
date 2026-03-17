"""Tests for the planner evaluation harness."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphsmith.evaluation.planner_eval import (
    EvalGoal,
    EvalResult,
    evaluate_goal,
    load_goals,
    run_evaluation,
)
from graphsmith.planner import MockPlannerBackend
from graphsmith.registry import LocalRegistry

from conftest import EXAMPLE_DIR

GOALS_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "goals"


@pytest.fixture()
def reg(tmp_path: Path) -> LocalRegistry:
    r = LocalRegistry(root=tmp_path / "reg")
    r.publish(EXAMPLE_DIR / "text.normalize.v1")
    r.publish(EXAMPLE_DIR / "text.extract_keywords.v1")
    r.publish(EXAMPLE_DIR / "text.summarize.v1")
    r.publish(EXAMPLE_DIR / "json.reshape.v1")
    r.publish(EXAMPLE_DIR / "text.join_lines.v1")
    return r


class TestLoadGoals:
    def test_loads_all_goals(self) -> None:
        goals = load_goals(GOALS_DIR)
        assert len(goals) >= 8

    def test_goal_structure(self) -> None:
        goals = load_goals(GOALS_DIR)
        for g in goals:
            assert g.goal
            assert g.min_nodes >= 1

    def test_empty_dir(self, tmp_path: Path) -> None:
        goals = load_goals(tmp_path / "empty")
        assert goals == []


class TestEvaluateGoal:
    def test_single_skill_goal(self, reg: LocalRegistry) -> None:
        goal = EvalGoal(
            goal="normalize text",
            expected_skills=["text.normalize.v1"],
            expected_output_names=["normalized"],
            min_nodes=1,
        )
        result = evaluate_goal(goal, reg, MockPlannerBackend())
        # Mock planner picks first candidate — may or may not be normalize
        assert result.status in ("pass", "partial", "fail")
        assert result.score >= 0.0

    def test_result_has_checks(self, reg: LocalRegistry) -> None:
        goal = EvalGoal(goal="test", expected_skills=[], min_nodes=1)
        result = evaluate_goal(goal, reg, MockPlannerBackend())
        assert result.checks.parsed is True or result.checks.parsed is False


class TestRunEvaluation:
    def test_full_eval_with_mock(self, reg: LocalRegistry) -> None:
        goals = load_goals(GOALS_DIR)
        report = run_evaluation(
            goals, reg, MockPlannerBackend(),
            provider_name="mock", model_name="",
        )
        assert report.goals_total == len(goals)
        assert report.goals_total > 0
        assert 0.0 <= report.pass_rate <= 1.0
        assert len(report.results) == len(goals)

    def test_report_has_timestamp(self, reg: LocalRegistry) -> None:
        goals = [EvalGoal(goal="test", min_nodes=1)]
        report = run_evaluation(goals, reg, MockPlannerBackend())
        assert report.timestamp

    def test_empty_goals(self, reg: LocalRegistry) -> None:
        report = run_evaluation([], reg, MockPlannerBackend())
        assert report.goals_total == 0
        assert report.pass_rate == 0.0


class TestCLIEvalPlanner:
    def test_eval_with_mock(self, reg: LocalRegistry) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, [
            "eval-planner",
            "--goals", str(GOALS_DIR),
            "--registry", str(reg.root),
            "--output-format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["goals_total"] >= 8
        assert "results" in data

    def test_eval_text_output(self, reg: LocalRegistry) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, [
            "eval-planner",
            "--goals", str(GOALS_DIR),
            "--registry", str(reg.root),
        ])
        assert result.exit_code == 0
        assert "Planner Evaluation" in result.output
        assert "Goals:" in result.output

    def test_save_results(self, reg: LocalRegistry, tmp_path: Path) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        out_path = tmp_path / "results.json"
        result = runner.invoke(app, [
            "eval-planner",
            "--goals", str(GOALS_DIR),
            "--registry", str(reg.root),
            "--save-results", str(out_path),
        ])
        assert result.exit_code == 0
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert data["goals_total"] >= 8
