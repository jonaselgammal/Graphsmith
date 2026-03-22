"""Tests for graph export, trace formatting, and inspection."""
from __future__ import annotations

from graphsmith.cli.interactive import (
    HELP_TEXT,
    format_candidates,
    format_compare,
    format_nodes,
    format_plan_summary,
    format_trace,
)
from graphsmith.graph_export import graph_to_ascii, graph_to_dot, graph_to_json
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.planner.ir import IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.ir_backend import CandidateResult
from graphsmith.planner.ir_scorer import ScoreBreakdown
from graphsmith.planner.models import GlueGraph
from graphsmith.traces.models import NodeTrace, RunTrace


def _make_glue() -> GlueGraph:
    return GlueGraph(
        goal="normalize and extract",
        inputs=[IOField(name="text", type="string")],
        outputs=[
            IOField(name="normalized", type="string"),
            IOField(name="keywords", type="string"),
        ],
        effects=["llm_inference"],
        graph=GraphBody(
            version=1,
            nodes=[
                GraphNode(id="normalize", op="skill.invoke",
                          config={"skill_id": "text.normalize.v1", "version": "1.0.0"}),
                GraphNode(id="extract", op="skill.invoke",
                          config={"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}),
            ],
            edges=[
                GraphEdge(from_="input.text", to="normalize.text"),
                GraphEdge(from_="normalize.normalized", to="extract.text"),
            ],
            outputs={"normalized": "normalize.normalized", "keywords": "extract.keywords"},
        ),
    )


def _make_trace() -> RunTrace:
    t = RunTrace(skill_id="test", started_at="t0", inputs_summary={"text": "hello"})
    t.nodes.append(NodeTrace(
        node_id="normalize", op="text.normalize", status="ok",
        started_at="t1", ended_at="t2",
        inputs_summary={"text": "hello"},
        outputs_summary={"normalized": "hello"},
    ))
    t.nodes.append(NodeTrace(
        node_id="extract", op="text.extract_keywords", status="ok",
        started_at="t3", ended_at="t4",
        inputs_summary={"text": "hello"},
        outputs_summary={"keywords": "hello"},
    ))
    t.status = "ok"
    t.ended_at = "t5"
    return t


# ── Graph export ──────────────────────────────────────────────────


class TestGraphToDot:
    def test_contains_nodes(self) -> None:
        dot = graph_to_dot(_make_glue())
        assert "normalize" in dot
        assert "extract" in dot

    def test_contains_edges(self) -> None:
        dot = graph_to_dot(_make_glue())
        assert "->" in dot

    def test_contains_inputs_outputs(self) -> None:
        dot = graph_to_dot(_make_glue())
        assert "Inputs" in dot
        assert "Outputs" in dot

    def test_valid_dot_syntax(self) -> None:
        dot = graph_to_dot(_make_glue())
        assert dot.startswith("digraph G {")
        assert dot.endswith("}")


class TestGraphToJson:
    def test_has_nodes(self) -> None:
        data = graph_to_json(_make_glue())
        assert len(data["nodes"]) == 2
        assert data["nodes"][0]["id"] == "normalize"

    def test_has_edges(self) -> None:
        data = graph_to_json(_make_glue())
        assert len(data["edges"]) == 2

    def test_has_outputs(self) -> None:
        data = graph_to_json(_make_glue())
        assert "normalized" in data["outputs"]
        assert "keywords" in data["outputs"]


class TestGraphToAscii:
    def test_shows_flow(self) -> None:
        text = graph_to_ascii(_make_glue())
        assert "normalize" in text
        assert "extract" in text
        assert "\u2192" in text  # arrow

    def test_shows_inputs_outputs(self) -> None:
        text = graph_to_ascii(_make_glue())
        assert "Inputs:" in text
        assert "Outputs:" in text


# ── Trace formatting ─────────────────────────────────────────────


class TestFormatTrace:
    def test_shows_steps(self) -> None:
        text = format_trace(_make_trace())
        assert "Step 1: normalize" in text
        assert "Step 2: extract" in text

    def test_shows_io(self) -> None:
        text = format_trace(_make_trace())
        assert "in.text:" in text
        assert "out.normalized:" in text

    def test_shows_status(self) -> None:
        text = format_trace(_make_trace())
        assert "ok" in text


# ── Node listing ─────────────────────────────────────────────────


class TestFormatNodes:
    def test_lists_nodes(self) -> None:
        text = format_nodes(_make_glue())
        assert "normalize:" in text
        assert "extract:" in text
        assert "text.normalize.v1" in text

    def test_lists_outputs(self) -> None:
        text = format_nodes(_make_glue())
        assert "Outputs:" in text
        assert "normalized" in text


# ── Help text ────────────────────────────────────────────────────


class TestHelpText:
    def test_includes_new_commands(self) -> None:
        assert ":trace" in HELP_TEXT
        assert ":inspect" in HELP_TEXT
        assert ":nodes" in HELP_TEXT
        assert ":graph" in HELP_TEXT


# ── Plan summary ─────────────────────────────────────────────────


class TestPlanSummary:
    def test_shows_flow_chain(self) -> None:
        text = format_plan_summary(_make_glue())
        assert "normalize \u2192 extract" in text

    def test_shows_steps(self) -> None:
        text = format_plan_summary(_make_glue())
        assert "1. normalize" in text
        assert "2. extract" in text
