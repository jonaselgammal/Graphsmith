"""Tests for plan execution: plan-and-run, save/load plans, run-plan."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from graphsmith.cli.main import app
from graphsmith.exceptions import ExecutionError, PlannerError
from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.planner import (
    GlueGraph,
    MockPlannerBackend,
    compose_plan,
    load_plan,
    run_glue_graph,
    save_plan,
)
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.registry import LocalRegistry

from conftest import EXAMPLE_DIR, minimal_examples, minimal_graph, minimal_skill, write_package

runner = CliRunner()


@pytest.fixture()
def reg(tmp_path: Path) -> LocalRegistry:
    r = LocalRegistry(root=tmp_path / "registry")
    r.publish(EXAMPLE_DIR / "text.summarize.v1")
    return r


@pytest.fixture()
def minimal_reg(tmp_path: Path) -> LocalRegistry:
    r = LocalRegistry(root=tmp_path / "registry")
    pkg_dir = tmp_path / "pkg"
    write_package(pkg_dir, skill=minimal_skill(), graph=minimal_graph(), examples=minimal_examples())
    r.publish(pkg_dir)
    return r


# ── run_glue_graph ───────────────────────────────────────────────────


class TestRunGlueGraph:
    def test_run_valid_plan(self, reg: LocalRegistry) -> None:
        result = compose_plan("summarize text", reg, MockPlannerBackend())
        assert result.status == "success" and result.graph is not None

        exec_result = run_glue_graph(
            result.graph,
            {"text": "Cats sleep", "max_sentences": 1},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=reg,
        )
        assert exec_result.trace.status == "ok"
        assert len(exec_result.outputs) > 0

    def test_run_minimal_plan(self, minimal_reg: LocalRegistry) -> None:
        result = compose_plan("test", minimal_reg, MockPlannerBackend())
        assert result.status == "success" and result.graph is not None

        exec_result = run_glue_graph(result.graph, {"text": "hello"}, registry=minimal_reg)
        assert exec_result.outputs == {"result": "hello"}

    def test_trace_has_glue_id(self, minimal_reg: LocalRegistry) -> None:
        result = compose_plan("test", minimal_reg, MockPlannerBackend())
        exec_result = run_glue_graph(result.graph, {"text": "x"}, registry=minimal_reg)
        assert exec_result.trace.skill_id.startswith("_glue.")

    def test_invalid_glue_raises(self) -> None:
        from graphsmith.models.common import IOField
        from graphsmith.models.graph import GraphBody, GraphNode

        bad_glue = GlueGraph(
            goal="bad",
            inputs=[IOField(name="x", type="string")],
            outputs=[IOField(name="y", type="string")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[GraphNode(id="n", op="magic.spell")],
                edges=[],
                outputs={"y": "n.out"},
            ),
        )
        with pytest.raises(PlannerError, match="validation failed"):
            run_glue_graph(bad_glue, {"x": "hello"})

    def test_partial_plan_not_executed(self, reg: LocalRegistry) -> None:
        """Compose a plan with desired_outputs that can't be met → partial."""
        from graphsmith.models.common import IOField
        result = compose_plan(
            "summarize text", reg, MockPlannerBackend(),
            desired_outputs=[IOField(name="nonexistent", type="string")],
        )
        assert result.status == "partial"
        # run_glue_graph only takes a GlueGraph, not a PlanResult.
        # Callers must check status before calling.


# ── save / load ──────────────────────────────────────────────────────


class TestSaveLoad:
    def test_save_and_load(self, reg: LocalRegistry, tmp_path: Path) -> None:
        result = compose_plan("summarize text", reg, MockPlannerBackend())
        assert result.graph is not None

        plan_path = tmp_path / "plan.json"
        save_plan(result.graph, plan_path)

        loaded = load_plan(plan_path)
        assert loaded.goal == result.graph.goal
        assert len(loaded.inputs) == len(result.graph.inputs)
        assert len(loaded.graph.nodes) == len(result.graph.graph.nodes)

    def test_saved_plan_is_valid_json(self, reg: LocalRegistry, tmp_path: Path) -> None:
        result = compose_plan("summarize text", reg, MockPlannerBackend())
        plan_path = tmp_path / "plan.json"
        save_plan(result.graph, plan_path)

        data = json.loads(plan_path.read_text())
        assert "goal" in data
        assert "inputs" in data
        assert "outputs" in data
        assert "graph" in data
        # It should NOT have skill_id, version, etc. (not a SkillPackage)
        assert "id" not in data
        assert "version" not in data

    def test_load_and_run(self, reg: LocalRegistry, tmp_path: Path) -> None:
        result = compose_plan("summarize text", reg, MockPlannerBackend())
        plan_path = tmp_path / "plan.json"
        save_plan(result.graph, plan_path)

        loaded = load_plan(plan_path)
        exec_result = run_glue_graph(
            loaded,
            {"text": "hello", "max_sentences": 1},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=reg,
        )
        assert exec_result.trace.status == "ok"

    def test_load_nonexistent(self) -> None:
        with pytest.raises(PlannerError, match="not found"):
            load_plan("/nonexistent/plan.json")

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        with pytest.raises(PlannerError, match="Failed to load"):
            load_plan(bad)


# ── CLI: plan --save ─────────────────────────────────────────────────


class TestCLIPlanSave:
    def test_plan_save(self, tmp_path: Path) -> None:
        reg_root = tmp_path / "reg"
        runner.invoke(app, [
            "publish", str(EXAMPLE_DIR / "text.summarize.v1"),
            "--registry", str(reg_root),
        ])
        plan_path = tmp_path / "my_plan.json"
        result = runner.invoke(app, [
            "plan", "summarize text",
            "--registry", str(reg_root),
            "--save", str(plan_path),
        ])
        assert result.exit_code == 0
        assert plan_path.exists()
        data = json.loads(plan_path.read_text())
        assert data["goal"] == "summarize text"


# ── CLI: plan-and-run ────────────────────────────────────────────────


class TestCLIPlanAndRun:
    def test_success(self, tmp_path: Path) -> None:
        reg_root = tmp_path / "reg"
        pkg_dir = tmp_path / "pkg"
        write_package(pkg_dir, skill=minimal_skill(), graph=minimal_graph(), examples=minimal_examples())
        runner.invoke(app, ["publish", str(pkg_dir), "--registry", str(reg_root)])

        result = runner.invoke(app, [
            "plan-and-run", "test",
            "--registry", str(reg_root),
            "--input", '{"text":"hello"}',
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == {"result": "hello"}

    def test_json_output(self, tmp_path: Path) -> None:
        reg_root = tmp_path / "reg"
        pkg_dir = tmp_path / "pkg"
        write_package(pkg_dir, skill=minimal_skill(), graph=minimal_graph(), examples=minimal_examples())
        runner.invoke(app, ["publish", str(pkg_dir), "--registry", str(reg_root)])

        result = runner.invoke(app, [
            "plan-and-run", "test",
            "--registry", str(reg_root),
            "--input", '{"text":"hi"}',
            "--output-format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "plan" in data
        assert "outputs" in data
        assert data["plan"]["status"] == "success"

    def test_empty_registry_fails(self, tmp_path: Path) -> None:
        result = runner.invoke(app, [
            "plan-and-run", "test",
            "--registry", str(tmp_path / "empty_reg"),
        ])
        assert result.exit_code == 1

    def test_trace_persisted(self, tmp_path: Path) -> None:
        reg_root = tmp_path / "reg"
        trace_root = tmp_path / "traces"
        pkg_dir = tmp_path / "pkg"
        write_package(pkg_dir, skill=minimal_skill(), graph=minimal_graph(), examples=minimal_examples())
        runner.invoke(app, ["publish", str(pkg_dir), "--registry", str(reg_root)])

        runner.invoke(app, [
            "plan-and-run", "test",
            "--registry", str(reg_root),
            "--input", '{"text":"hi"}',
            "--trace-root", str(trace_root),
        ])
        traces = list(trace_root.glob("*.json"))
        assert len(traces) == 1


# ── CLI: run-plan ────────────────────────────────────────────────────


class TestCLIRunPlan:
    def test_run_saved_plan(self, tmp_path: Path) -> None:
        reg_root = tmp_path / "reg"
        pkg_dir = tmp_path / "pkg"
        write_package(pkg_dir, skill=minimal_skill(), graph=minimal_graph(), examples=minimal_examples())
        runner.invoke(app, ["publish", str(pkg_dir), "--registry", str(reg_root)])

        # Save plan
        plan_path = tmp_path / "plan.json"
        runner.invoke(app, [
            "plan", "test",
            "--registry", str(reg_root),
            "--save", str(plan_path),
        ])
        assert plan_path.exists()

        # Run saved plan
        result = runner.invoke(app, [
            "run-plan", str(plan_path),
            "--input", '{"text":"world"}',
            "--registry", str(reg_root),
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == {"result": "world"}

    def test_run_nonexistent_plan(self, tmp_path: Path) -> None:
        result = runner.invoke(app, [
            "run-plan", str(tmp_path / "nope.json"),
            "--input", '{"text":"x"}',
        ])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "FAIL" in result.output

    def test_run_invalid_plan(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        result = runner.invoke(app, [
            "run-plan", str(bad),
            "--input", '{"text":"x"}',
        ])
        assert result.exit_code == 1
