"""Tests for the stress frontier evaluation harness."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from typer.testing import CliRunner

from graphsmith.cli.main import app
from graphsmith.evaluation.stress_eval import (
    StressCase,
    StressCaseResult,
    StressReport,
    evaluate_stress_case,
    load_stress_cases,
    run_stress_suite,
)
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphNode
from graphsmith.planner.models import GlueGraph
from graphsmith.registry.local import LocalRegistry
from graphsmith.skills.autogen import SkillSpec
from graphsmith.skills.closed_loop import ClosedLoopResult


STRESS_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "stress_frontier_goals"
PROGRAMMING_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "programming_replacement_goals"


def test_load_stress_cases() -> None:
    cases = load_stress_cases(STRESS_DIR)
    assert len(cases) == 12
    assert cases[0].id == "s01"
    assert cases[-1].id == "s12"


def test_load_programming_replacement_cases() -> None:
    cases = load_stress_cases(PROGRAMMING_DIR)
    assert len(cases) == 13
    assert cases[0].id == "p01"
    assert cases[-1].id == "p13"


def test_run_stress_suite_aggregates_results(monkeypatch) -> None:
    def fake_evaluate(case, registry, backend, *, trace_store=None):
        return StressCaseResult(
            id=case.id,
            goal=case.goal,
            tier=case.tier,
            status="pass" if case.expected_success else "fail",
            expected_success=case.expected_success,
            observed_success=case.expected_success,
            generated_skill_id="text.contains.v1" if case.expected_success else "",
            stopped_reason="replan_succeeded" if case.expected_success else "replan_failed",
        )

    monkeypatch.setattr("graphsmith.evaluation.stress_eval.evaluate_stress_case", fake_evaluate)

    with tempfile.TemporaryDirectory() as tmpdir:
        registry = LocalRegistry(tmpdir)
        report = run_stress_suite(
            [
                StressCase(id="a", goal="one", expected_success=True),
                StressCase(id="b", goal="two", expected_success=False),
            ],
            registry=registry,
            backend=object(),
            provider_name="mock",
            model_name="tiny",
            mode="isolated",
        )

    assert report.total == 2
    assert report.passed == 1
    assert report.mode == "isolated"
    assert report.provider == "mock"
    assert report.generated_cases == 1


def test_evaluate_stress_case_checks_required_ops(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = LocalRegistry(tmpdir)

        def fake_run_closed_loop(goal, backend, registry, *, output_dir=None, auto_approve=False, confirm_fn=None):
            graph = GlueGraph(
                goal=goal,
                inputs=[IOField(name="items", type="array<string>")],
                outputs=[IOField(name="normalized", type="array<string>")],
                effects=["pure"],
                graph=GraphBody(
                    version=1,
                    nodes=[GraphNode(id="loop", op="parallel.map", config={})],
                    edges=[],
                    outputs={"normalized": "loop.normalized"},
                ),
            )
            return ClosedLoopResult(
                initial_status="failure",
                replan_status="success",
                replan_plan=graph,
                stopped_reason="replan_succeeded",
                success=True,
                generated_spec=SkillSpec(
                    skill_id="text.normalize.v1",
                    op_name="text_normalize_v1",
                    category="text",
                    short_name="normalize",
                    human_name="Normalize",
                    description="Normalize text.",
                    template_key="normalize",
                    family="text_transform",
                    inputs=[{"name": "text", "type": "string"}],
                    outputs=[{"name": "normalized", "type": "string"}],
                    examples=[],
                ),
            )

        monkeypatch.setattr("graphsmith.evaluation.stress_eval.run_closed_loop", fake_run_closed_loop)

        case = StressCase(
            id="x",
            goal="normalize each item",
            expected_success=True,
            required_ops=["parallel.map"],
            require_generated_skill=True,
        )
        result = evaluate_stress_case(case, registry, backend=object())

    assert result.status == "pass"
    assert result.generated_skill_used_in_plan is False
    assert result.node_count == 1


def test_eval_stress_frontier_cli_json(monkeypatch, tmp_path: Path) -> None:
    goals_dir = tmp_path / "goals"
    goals_dir.mkdir()
    (goals_dir / "case.json").write_text(
        json.dumps({"id": "s1", "goal": "normalize and count", "expected_success": True}),
        encoding="utf-8",
    )

    def fake_run_stress_suite(cases, registry, backend, *, provider_name="", model_name="", mode="isolated"):
        return StressReport(
            provider=provider_name,
            model=model_name,
            mode=mode,
            total=1,
            passed=1,
            pass_rate=1.0,
            results=[
                StressCaseResult(
                    id="s1",
                    goal="normalize and count",
                    tier=1,
                    status="pass",
                    expected_success=True,
                    observed_success=True,
                )
            ],
        )

    monkeypatch.setattr("graphsmith.evaluation.stress_eval.run_stress_suite", fake_run_stress_suite)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "eval-stress-frontier",
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
