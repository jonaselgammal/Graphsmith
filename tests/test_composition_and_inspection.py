"""Tests for Sprint 18: formatting-chain composition and plan inspection."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from graphsmith.cli.main import app
from graphsmith.planner import load_plan
from graphsmith.planner.models import GlueGraph, PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import PROMPT_VERSION, build_planning_context
from graphsmith.planner.render import render_plan_mermaid, render_plan_text
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.registry.index import IndexEntry
from graphsmith.validator import validate_skill_package

from conftest import EXAMPLE_DIR

runner = CliRunner()

PLANS_DIR = Path(__file__).resolve().parent.parent / "examples" / "plans"


# ── prompt content ───────────────────────────────────────────────────


class TestPromptFormattingGuidance:
    def test_version_v4(self) -> None:
        assert PROMPT_VERSION == "v6"

    def test_has_formatting_chain_example(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "extract_keywords" in ctx
        assert "join_lines" in ctx
        assert "format" in ctx

    def test_example_shows_extraction_to_formatting(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "extract.keywords" in ctx
        assert "format.lines" in ctx

    def test_candidate_tags_shown(self) -> None:
        entry = IndexEntry(
            id="test.v1", name="Test", version="1.0.0",
            description="test", tags=["formatting", "text"],
            input_names=["x"], output_names=["y"],
        )
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[entry]))
        assert "formatting" in ctx
        assert "tags:" in ctx.lower()


# ── formatting-chain plan patterns ───────────────────────────────────


class TestFormattingChainPlans:
    def test_extract_then_format(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "joined", "type": "string"}],
            "nodes": [
                {"id": "extract", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
                {"id": "format", "op": "skill.invoke",
                 "config": {"skill_id": "text.join_lines.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "extract.text"},
                {"from": "extract.keywords", "to": "format.lines"},
            ],
            "graph_outputs": {"joined": "format.joined"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)

    def test_normalize_extract_format(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "joined", "type": "string"}],
            "nodes": [
                {"id": "norm", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
                {"id": "extract", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
                {"id": "format", "op": "skill.invoke",
                 "config": {"skill_id": "text.join_lines.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "norm.text"},
                {"from": "norm.normalized", "to": "extract.text"},
                {"from": "extract.keywords", "to": "format.lines"},
            ],
            "graph_outputs": {"joined": "format.joined"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
        assert len(result.graph.graph.nodes) == 3


# ── plan rendering ───────────────────────────────────────────────────


@pytest.fixture()
def sample_glue() -> GlueGraph:
    return GlueGraph(
        goal="normalize and extract",
        inputs=[IOField(name="text", type="string")],
        outputs=[IOField(name="keywords", type="string")],
        effects=["llm_inference"],
        graph=GraphBody(
            version=1,
            nodes=[
                GraphNode(id="norm", op="skill.invoke",
                          config={"skill_id": "text.normalize.v1", "version": "1.0.0"}),
                GraphNode(id="kw", op="skill.invoke",
                          config={"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}),
            ],
            edges=[
                GraphEdge(from_="input.text", to="norm.text"),
                GraphEdge(from_="norm.normalized", to="kw.text"),
            ],
            outputs={"keywords": "kw.keywords"},
        ),
    )


class TestRenderText:
    def test_contains_goal(self, sample_glue: GlueGraph) -> None:
        text = render_plan_text(sample_glue)
        assert "normalize and extract" in text

    def test_contains_nodes(self, sample_glue: GlueGraph) -> None:
        text = render_plan_text(sample_glue)
        assert "norm" in text
        assert "kw" in text

    def test_contains_edges(self, sample_glue: GlueGraph) -> None:
        text = render_plan_text(sample_glue)
        assert "input.text" in text
        assert "norm.text" in text

    def test_contains_outputs(self, sample_glue: GlueGraph) -> None:
        text = render_plan_text(sample_glue)
        assert "keywords" in text


class TestRenderMermaid:
    def test_is_mermaid_block(self, sample_glue: GlueGraph) -> None:
        md = render_plan_mermaid(sample_glue)
        assert md.startswith("```mermaid")
        assert md.endswith("```")

    def test_contains_flowchart(self, sample_glue: GlueGraph) -> None:
        md = render_plan_mermaid(sample_glue)
        assert "flowchart TD" in md

    def test_contains_nodes(self, sample_glue: GlueGraph) -> None:
        md = render_plan_mermaid(sample_glue)
        assert "norm" in md
        assert "kw" in md

    def test_contains_edges(self, sample_glue: GlueGraph) -> None:
        md = render_plan_mermaid(sample_glue)
        assert "Inputs" in md
        assert "Outputs" in md
        assert "-->" in md

    def test_deterministic(self, sample_glue: GlueGraph) -> None:
        a = render_plan_mermaid(sample_glue)
        b = render_plan_mermaid(sample_glue)
        assert a == b


# ── CLI commands ─────────────────────────────────────────────────────


class TestShowPlanCLI:
    def test_show_plan(self) -> None:
        result = runner.invoke(app, [
            "show-plan", str(PLANS_DIR / "normalize_extract_keywords.json"),
        ])
        assert result.exit_code == 0
        assert "normalize" in result.output
        assert "extract" in result.output

    def test_render_plan_mermaid(self) -> None:
        result = runner.invoke(app, [
            "render-plan", str(PLANS_DIR / "normalize_extract_keywords.json"),
        ])
        assert result.exit_code == 0
        assert "```mermaid" in result.output
        assert "flowchart TD" in result.output

    def test_render_plan_text(self) -> None:
        result = runner.invoke(app, [
            "render-plan", str(PLANS_DIR / "normalize_extract_keywords.json"),
            "--format", "text",
        ])
        assert result.exit_code == 0
        assert "Plan:" in result.output

    def test_show_nonexistent(self) -> None:
        result = runner.invoke(app, ["show-plan", "/nonexistent.json"])
        assert result.exit_code == 1
