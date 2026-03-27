"""Tests for the frontier evaluation harness."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from typer.testing import CliRunner

from graphsmith.cli.main import app
from graphsmith.evaluation.frontier_eval import (
    FrontierCase,
    FrontierCaseResult,
    FrontierReport,
    evaluate_frontier_case,
    load_frontier_cases,
    run_frontier_suite,
)
from graphsmith.registry.local import LocalRegistry
from graphsmith.skills.autogen import SkillSpec
from graphsmith.skills.closed_loop import ClosedLoopResult
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphNode
from graphsmith.planner.models import GlueGraph


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
        graph = GlueGraph(
            goal=goal,
            inputs=[IOField(name="numbers", type="array<number>")],
            outputs=[IOField(name="median", type="number")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[GraphNode(id="s1", op="skill.invoke", config={"skill_id": "math.median.v1"})],
                edges=[],
                outputs={"median": "s1.median"},
            ),
        )
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
            replan_plan=graph,
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


def test_evaluate_frontier_case_isolates_registry_per_case(monkeypatch) -> None:
    seen_roots: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = LocalRegistry(tmpdir)

        def fake_run_closed_loop(goal, backend, registry, *, output_dir=None, auto_approve=False, confirm_fn=None):
            seen_roots.append(str(registry.root))
            return ClosedLoopResult(initial_status="failure", stopped_reason="missing_skill_not_detected")

        monkeypatch.setattr("graphsmith.evaluation.frontier_eval.run_closed_loop", fake_run_closed_loop)

        case = FrontierCase(id="x", goal="goal")
        evaluate_frontier_case(case, registry, backend=object())

    assert seen_roots
    assert seen_roots[0] != str(registry.root)


def test_evaluate_frontier_case_checks_structure(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = LocalRegistry(tmpdir)

        def fake_run_closed_loop(goal, backend, registry, *, output_dir=None, auto_approve=False, confirm_fn=None):
            graph = GlueGraph(
                goal=goal,
                inputs=[IOField(name="text", type="string")],
                outputs=[IOField(name="uppercased", type="string")],
                effects=["pure"],
                graph=GraphBody(
                    version=1,
                    nodes=[GraphNode(id="s1", op="skill.invoke", config={"skill_id": "text.uppercase.v1"})],
                    edges=[],
                    outputs={"uppercased": "s1.uppercased"},
                ),
            )
            return ClosedLoopResult(
                initial_status="failure",
                replan_status="success",
                replan_plan=graph,
                stopped_reason="multi_stage_fallback_succeeded",
                success=True,
            )

        monkeypatch.setattr("graphsmith.evaluation.frontier_eval.run_closed_loop", fake_run_closed_loop)

        case = FrontierCase(
            id="x",
            goal="normalize and uppercase",
            expected_success=True,
            required_skill_ids=["text.normalize.v1", "text.uppercase.v1"],
            min_node_count=2,
        )
        result = evaluate_frontier_case(case, registry, backend=object())

    assert result.status == "fail"
    assert not result.structural_pass
    assert "missing_required_skill:text.normalize.v1" in result.structural_failures


def test_evaluate_frontier_case_checks_required_inputs(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = LocalRegistry(tmpdir)

        def fake_run_closed_loop(goal, backend, registry, *, output_dir=None, auto_approve=False, confirm_fn=None):
            graph = GlueGraph(
                goal=goal,
                inputs=[IOField(name="text", type="string"), IOField(name="prefix", type="string")],
                outputs=[IOField(name="result", type="string")],
                effects=["pure"],
                graph=GraphBody(
                    version=1,
                    nodes=[GraphNode(id="s1", op="skill.invoke", config={"skill_id": "text.starts_with.v1"})],
                    edges=[],
                    outputs={"result": "s1.result"},
                ),
            )
            return ClosedLoopResult(
                initial_status="failure",
                replan_status="success",
                replan_plan=graph,
                stopped_reason="multi_stage_fallback_succeeded",
                success=True,
                generated_spec=SkillSpec(
                    skill_id="text.starts_with.v1",
                    op_name="text.starts_with",
                    category="text",
                    short_name="starts_with",
                    human_name="Starts With",
                    description="Check if text starts with a prefix value.",
                    template_key="starts_with",
                    family="text_binary_predicate",
                    inputs=[{"name": "text", "type": "string"}, {"name": "prefix", "type": "string"}],
                    outputs=[{"name": "result", "type": "string"}],
                    examples=[{"input": {"text": "hello", "prefix": "he"}, "output": {"result": "true"}}],
                ),
            )

        monkeypatch.setattr("graphsmith.evaluation.frontier_eval.run_closed_loop", fake_run_closed_loop)

        case = FrontierCase(
            id="y",
            goal="starts with prefix",
            expected_success=True,
            required_graph_inputs=["prefix"],
            require_generated_skill=True,
        )
        result = evaluate_frontier_case(case, registry, backend=object())

    assert result.status == "pass"
    assert result.structural_pass
