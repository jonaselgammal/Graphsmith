"""Tests for Sprint 33: failing plan capture + contract/config fidelity."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphsmith.evaluation.planner_eval import EvalGoal, EvalResult, evaluate_goal, load_goals
from graphsmith.planner import MockPlannerBackend
from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import build_planning_context
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.registry import LocalRegistry
from graphsmith.validator import validate_skill_package
from graphsmith.exceptions import ValidationError

from conftest import EXAMPLE_DIR


@pytest.fixture()
def full_reg(tmp_path: Path) -> LocalRegistry:
    r = LocalRegistry(root=tmp_path / "reg")
    for d in sorted((EXAMPLE_DIR).iterdir()):
        if d.is_dir():
            r.publish(d)
    return r


# ── plan capture ─────────────────────────────────────────────────────


class TestPlanCapture:
    def test_eval_result_has_plan_json(self, full_reg: LocalRegistry) -> None:
        goal = EvalGoal(goal="normalize text", expected_skills=["text.normalize.v1"])
        result = evaluate_goal(goal, full_reg, MockPlannerBackend())
        # Mock planner produces a graph, so plan_json should be populated
        assert result.plan_json is not None
        assert "nodes" in result.plan_json.get("graph", {})

    def test_cli_save_failed_plans(self, full_reg: LocalRegistry, tmp_path: Path) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        out_dir = tmp_path / "failed"
        result = runner.invoke(app, [
            "eval-planner",
            "--goals", "evaluation/holdout_goals",
            "--registry", str(full_reg.root),
            "--save-failed-plans", str(out_dir),
        ])
        assert result.exit_code == 0
        # Some goals will fail with mock planner, so files should exist
        # (or directory should be created)
        assert out_dir.exists()


# ── config fidelity ──────────────────────────────────────────────────


class TestConfigFidelity:
    def test_prompt_prohibits_config_edges(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert 'config.X' in ctx or '"config" is not a graph scope' in ctx

    def test_config_header_edge_fails_validation(self) -> None:
        """A plan using config.header as an edge source must fail validation."""
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "formatted", "type": "string"}],
            "nodes": [
                {"id": "extract", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
                {"id": "format", "op": "template.render",
                 "config": {"template": "{{header}}\n{{text}}"}},
            ],
            "edges": [
                {"from": "input.text", "to": "extract.text"},
                {"from": "extract.keywords", "to": "format.text"},
                {"from": "config.header", "to": "format.header"},
            ],
            "graph_outputs": {"formatted": "format.rendered"},
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.graph is not None
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError, match="config"):
            validate_skill_package(pkg)

    def test_correct_constant_header_validates(self) -> None:
        """A plan with header in config.template should validate."""
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "formatted", "type": "string"}],
            "nodes": [
                {"id": "extract", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
                {"id": "format", "op": "template.render",
                 "config": {"template": "Results:\n{{text}}"}},
            ],
            "edges": [
                {"from": "input.text", "to": "extract.text"},
                {"from": "extract.keywords", "to": "format.text"},
            ],
            "graph_outputs": {"formatted": "format.rendered"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)


# ── output contract fidelity ─────────────────────────────────────────


class TestOutputContractFidelity:
    def test_keywords_not_topics(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "keywords", "type": "string"}],
            "nodes": [
                {"id": "extract", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
            ],
            "edges": [{"from": "input.text", "to": "extract.text"}],
            "graph_outputs": {"keywords": "extract.keywords"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="find topics")
        assert result.status == "success"
        assert "keywords" in result.graph.graph.outputs

    def test_prompt_has_output_port_naming_rule(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "output_ports" in ctx or "port name" in ctx.lower()
        assert "NEVER invent" in ctx
