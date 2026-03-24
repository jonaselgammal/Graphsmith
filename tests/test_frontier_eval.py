"""Tests for the frontier evaluation harness."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from graphsmith.cli.main import app
from graphsmith.evaluation.frontier_eval import (
    FrontierCase,
    FrontierCaseResult,
    FrontierReport,
    load_frontier_cases,
    run_frontier_suite,
)
from graphsmith.skills.autogen import SkillSpec
from graphsmith.skills.closed_loop import ClosedLoopResult


FRONTIER_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "frontier_goals"


def test_load_frontier_cases() -> None:
    cases = load_frontier_cases(FRONTIER_DIR)
    assert len(cases) == 12
    assert cases[0].id == "f01"
    assert cases[-1].id == "f12"


def test_run_frontier_suite_aggregates_results(monkeypatch) -> None:
    def fake_evaluate(case, registry, backend):
        return FrontierCaseResult(
            id=case.id,
            goal=case.goal,
            tier=case.tier,
            status="pass" if case.expected_success else "fail",
            expected_success=case.expected_success,
            observed_success=case.expected_success,
        )

    monkeypatch.setattr("graphsmith.evaluation.frontier_eval.evaluate_frontier_case", fake_evaluate)

    report = run_frontier_suite(
        [
            FrontierCase(id="a", goal="one", expected_success=True),
            FrontierCase(id="b", goal="two", expected_success=False),
        ],
        registry=object(),
        backend=object(),
        provider_name="mock",
        model_name="tiny",
    )

    assert report.total == 2
    assert report.passed == 1
    assert report.pass_rate == 0.5
    assert report.provider == "mock"
    assert report.model == "tiny"


def test_eval_frontier_cli_json(monkeypatch, tmp_path: Path) -> None:
    goals_dir = tmp_path / "goals"
    goals_dir.mkdir()
    (goals_dir / "case.json").write_text(
        json.dumps(
            {
                "id": "case1",
                "goal": "compute median",
                "tier": 1,
                "expected_success": True,
            }
        ),
        encoding="utf-8",
    )

    def fake_run_closed_loop(goal, backend, registry, *, output_dir=None, auto_approve=False, confirm_fn=None):
        return ClosedLoopResult(
            initial_status="failure",
            detected_missing=True,
            generated_spec=SkillSpec(
                skill_id="math.median.v1",
                op_name="math_median_v1",
                category="math",
                short_name="median",
                human_name="Median",
                description="Compute the median of a list of numbers.",
                template_key="median_numbers",
                family="math_list",
                inputs=[{"name": "numbers", "type": "array<number>"}],
                outputs=[{"name": "median", "type": "number"}],
                examples=[{"input": {"numbers": "1\n2\n3"}, "output": {"median": "2"}}],
            ),
            replan_status="success",
            stopped_reason="replan_succeeded",
            success=True,
        )

    monkeypatch.setattr("graphsmith.evaluation.frontier_eval.run_closed_loop", fake_run_closed_loop)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval-frontier",
            "--goals",
            str(goals_dir),
            "--registry",
            str(tmp_path / "reg"),
            "--output-format",
            "json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["total"] == 1
    assert data["passed"] == 1
    assert data["results"][0]["generated_skill_id"] == "math.median.v1"
