"""Tests for expanded skill library and multi-skill composition."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.parser import load_skill_package
from graphsmith.planner import (
    MockPlannerBackend,
    compose_plan,
    run_glue_graph,
    save_plan,
    load_plan,
)
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.planner.models import GlueGraph
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.registry import LocalRegistry
from graphsmith.runtime import run_skill_package
from graphsmith.traces import TraceStore, find_promotion_candidates
from graphsmith.validator import validate_skill_package

from conftest import EXAMPLE_DIR


ALL_SKILL_DIRS = [
    EXAMPLE_DIR / "text.normalize.v1",
    EXAMPLE_DIR / "text.extract_keywords.v1",
    EXAMPLE_DIR / "json.reshape.v1",
    EXAMPLE_DIR / "text.join_lines.v1",
    EXAMPLE_DIR / "text.summarize.v1",
]


@pytest.fixture()
def full_reg(tmp_path: Path) -> LocalRegistry:
    """Registry with all example skills published."""
    reg = LocalRegistry(root=tmp_path / "registry")
    for d in ALL_SKILL_DIRS:
        reg.publish(d)
    return reg


# ── new skill validation ─────────────────────────────────────────────


class TestNewSkillValidation:
    @pytest.mark.parametrize("skill_dir", [
        EXAMPLE_DIR / "text.normalize.v1",
        EXAMPLE_DIR / "text.extract_keywords.v1",
        EXAMPLE_DIR / "json.reshape.v1",
        EXAMPLE_DIR / "text.join_lines.v1",
    ])
    def test_validates(self, skill_dir: Path) -> None:
        pkg = load_skill_package(skill_dir)
        validate_skill_package(pkg)


# ── new skill execution ──────────────────────────────────────────────


class TestNewSkillExecution:
    def test_normalize(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.normalize.v1")
        validate_skill_package(pkg)
        result = run_skill_package(pkg, {"text": "  Hello   World  "})
        assert result.outputs["normalized"] == "hello world"

    def test_extract_keywords(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.extract_keywords.v1")
        validate_skill_package(pkg)
        provider = EchoLLMProvider(prefix="")
        result = run_skill_package(
            pkg, {"text": "machine learning"}, llm_provider=provider,
        )
        assert "machine learning" in result.outputs["keywords"]

    def test_json_reshape(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "json.reshape.v1")
        validate_skill_package(pkg)
        result = run_skill_package(
            pkg, {"raw_json": '{"name":"Alice","value":42,"extra":"x"}'},
        )
        assert result.outputs["selected"] == {"name": "Alice", "value": 42}

    def test_join_lines(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.join_lines.v1")
        validate_skill_package(pkg)
        result = run_skill_package(
            pkg, {"lines": '["a","b","c"]'},
        )
        assert result.outputs["joined"] == 'Keywords:\n["a","b","c"]'


# ── multi-skill composition via canned glue graphs ───────────────────


class TestMultiSkillComposition:
    def test_normalize_then_summarize(self, full_reg: LocalRegistry) -> None:
        """Chain: text.normalize.v1 → text.summarize.v1."""
        glue = GlueGraph(
            goal="normalize then summarize",
            inputs=[
                IOField(name="text", type="string"),
                IOField(name="max_sentences", type="integer"),
            ],
            outputs=[IOField(name="summary", type="string")],
            effects=["llm_inference"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="norm",
                        op="skill.invoke",
                        config={"skill_id": "text.normalize.v1", "version": "1.0.0"},
                    ),
                    GraphNode(
                        id="sum",
                        op="skill.invoke",
                        config={"skill_id": "text.summarize.v1", "version": "1.0.0"},
                    ),
                ],
                edges=[
                    GraphEdge(from_="input.text", to="norm.text"),
                    GraphEdge(from_="norm.normalized", to="sum.text"),
                    GraphEdge(from_="input.max_sentences", to="sum.max_sentences"),
                ],
                outputs={"summary": "sum.summary"},
            ),
        )

        # Validate
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

        # Execute
        result = run_glue_graph(
            glue,
            {"text": "Cats sleep a lot", "max_sentences": 1},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=full_reg,
        )
        assert result.trace.status == "ok"
        assert "summary" in result.outputs
        assert "cats sleep a lot" in result.outputs["summary"]

    def test_normalize_then_keywords(self, full_reg: LocalRegistry) -> None:
        """Chain: text.normalize.v1 → text.extract_keywords.v1."""
        glue = GlueGraph(
            goal="normalize then extract keywords",
            inputs=[IOField(name="text", type="string")],
            outputs=[IOField(name="keywords", type="string")],
            effects=["llm_inference"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="norm",
                        op="skill.invoke",
                        config={"skill_id": "text.normalize.v1", "version": "1.0.0"},
                    ),
                    GraphNode(
                        id="kw",
                        op="skill.invoke",
                        config={"skill_id": "text.extract_keywords.v1", "version": "1.0.0"},
                    ),
                ],
                edges=[
                    GraphEdge(from_="input.text", to="norm.text"),
                    GraphEdge(from_="norm.normalized", to="kw.text"),
                ],
                outputs={"keywords": "kw.keywords"},
            ),
        )

        result = run_glue_graph(
            glue,
            {"text": "Machine Learning"},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=full_reg,
        )
        assert result.trace.status == "ok"
        assert "machine learning" in result.outputs["keywords"]

    def test_multi_skill_trace_has_children(self, full_reg: LocalRegistry) -> None:
        """Verify nested traces are present for multi-skill chains."""
        glue = GlueGraph(
            goal="chain test",
            inputs=[IOField(name="text", type="string")],
            outputs=[IOField(name="keywords", type="string")],
            effects=["llm_inference"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="norm",
                        op="skill.invoke",
                        config={"skill_id": "text.normalize.v1", "version": "1.0.0"},
                    ),
                    GraphNode(
                        id="kw",
                        op="skill.invoke",
                        config={"skill_id": "text.extract_keywords.v1", "version": "1.0.0"},
                    ),
                ],
                edges=[
                    GraphEdge(from_="input.text", to="norm.text"),
                    GraphEdge(from_="norm.normalized", to="kw.text"),
                ],
                outputs={"keywords": "kw.keywords"},
            ),
        )
        result = run_glue_graph(
            glue, {"text": "hello"},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=full_reg,
        )
        # Both nodes should have child traces
        assert len(result.trace.nodes) == 2
        for node_trace in result.trace.nodes:
            assert node_trace.child_trace is not None


# ── plan-and-run over full registry ──────────────────────────────────


class TestPlanAndRunMultiSkill:
    def test_plan_with_full_registry(self, full_reg: LocalRegistry) -> None:
        result = compose_plan("normalize text", full_reg, MockPlannerBackend())
        assert result.status == "success"
        assert result.graph is not None
        assert len(result.candidates_considered) >= 1

    def test_plan_and_execute(self, full_reg: LocalRegistry) -> None:
        result = compose_plan("normalize text", full_reg, MockPlannerBackend())
        assert result.graph is not None
        exec_result = run_glue_graph(
            result.graph,
            {"text": "Hello"},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=full_reg,
        )
        assert exec_result.trace.status == "ok"

    def test_traces_and_promotion(
        self, full_reg: LocalRegistry, tmp_path: Path,
    ) -> None:
        store = TraceStore(root=tmp_path / "traces")

        # Run the same multi-skill workflow twice
        glue = GlueGraph(
            goal="normalize then summarize",
            inputs=[
                IOField(name="text", type="string"),
                IOField(name="max_sentences", type="integer"),
            ],
            outputs=[IOField(name="summary", type="string")],
            effects=["llm_inference"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(id="norm", op="skill.invoke",
                              config={"skill_id": "text.normalize.v1", "version": "1.0.0"}),
                    GraphNode(id="sum", op="skill.invoke",
                              config={"skill_id": "text.summarize.v1", "version": "1.0.0"}),
                ],
                edges=[
                    GraphEdge(from_="input.text", to="norm.text"),
                    GraphEdge(from_="norm.normalized", to="sum.text"),
                    GraphEdge(from_="input.max_sentences", to="sum.max_sentences"),
                ],
                outputs={"summary": "sum.summary"},
            ),
        )

        for i in range(3):
            r = run_glue_graph(
                glue,
                {"text": f"run {i}", "max_sentences": 1},
                llm_provider=EchoLLMProvider(prefix=""),
                registry=full_reg,
            )
            store.save(r.trace)

        candidates = find_promotion_candidates(store, min_frequency=2)
        assert len(candidates) >= 1
        # The repeated signature is skill.invoke -> skill.invoke
        sigs = [c.signature for c in candidates]
        assert "skill.invoke -> skill.invoke" in sigs


# ── publish-time dependency warnings ─────────────────────────────────


class TestDependencyWarnings:
    def test_no_warnings_for_self_contained(self, tmp_path: Path) -> None:
        reg = LocalRegistry(root=tmp_path / "reg")
        _, warnings = reg.publish(EXAMPLE_DIR / "text.normalize.v1")
        assert warnings == []

    def test_warning_for_missing_dependency(self, tmp_path: Path) -> None:
        """literature.quick_review depends on skills not in the registry."""
        reg = LocalRegistry(root=tmp_path / "reg")
        _, warnings = reg.publish(EXAMPLE_DIR / "literature.quick_review.v1")
        assert len(warnings) >= 1
        assert any("search.arxiv.v1" in w for w in warnings)

    def test_no_warning_for_primitive_op_deps(self, tmp_path: Path) -> None:
        """extract_keywords depends on llm.generate (a primitive op)."""
        reg = LocalRegistry(root=tmp_path / "reg")
        _, warnings = reg.publish(EXAMPLE_DIR / "text.extract_keywords.v1")
        assert warnings == []

    def test_cli_shows_warnings(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        reg_root = tmp_path / "reg"
        result = runner.invoke(app, [
            "publish",
            str(EXAMPLE_DIR / "literature.quick_review.v1"),
            "--registry", str(reg_root),
        ])
        assert result.exit_code == 0
        assert "Published" in result.output
        # Warning should appear on stderr (captured in output by CliRunner)
