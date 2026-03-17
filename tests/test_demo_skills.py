"""Tests for Sprint 12 demo skill improvements and flagship workflow."""
from __future__ import annotations

from pathlib import Path

import pytest

from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.ops.text_ops import text_normalize
from graphsmith.exceptions import OpError
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.parser import load_skill_package
from graphsmith.planner import run_glue_graph
from graphsmith.planner.models import GlueGraph
from graphsmith.registry import LocalRegistry
from graphsmith.runtime import run_skill_package
from graphsmith.validator import validate_skill_package

from conftest import EXAMPLE_DIR


# ── text.normalize op unit tests ─────────────────────────────────────


class TestTextNormalizeOp:
    def test_strip_and_lowercase(self) -> None:
        result = text_normalize({}, {"text": "  Hello World  "})
        assert result == {"normalized": "hello world"}

    def test_collapse_spaces(self) -> None:
        result = text_normalize({}, {"text": "  AI   agents   ARE  "})
        assert result == {"normalized": "ai agents are"}

    def test_tabs_and_newlines(self) -> None:
        result = text_normalize({}, {"text": "hello\t\n  world"})
        assert result == {"normalized": "hello world"}

    def test_empty_string(self) -> None:
        result = text_normalize({}, {"text": ""})
        assert result == {"normalized": ""}

    def test_already_clean(self) -> None:
        result = text_normalize({}, {"text": "already clean"})
        assert result == {"normalized": "already clean"}

    def test_missing_input(self) -> None:
        with pytest.raises(OpError, match="requires input"):
            text_normalize({}, {})


# ── text.normalize.v1 skill ──────────────────────────────────────────


class TestNormalizeSkill:
    def test_validates(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.normalize.v1")
        validate_skill_package(pkg)

    def test_normalizes_whitespace_and_case(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.normalize.v1")
        result = run_skill_package(
            pkg,
            {"text": "  AI   agents are transforming SOFTWARE engineering  "},
        )
        assert result.outputs["normalized"] == "ai agents are transforming software engineering"

    def test_simple_input(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.normalize.v1")
        result = run_skill_package(pkg, {"text": "  Hello World  "})
        assert result.outputs["normalized"] == "hello world"


# ── text.extract_keywords.v1 skill ──────────────────────────────────


class TestExtractKeywordsSkill:
    def test_validates(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.extract_keywords.v1")
        validate_skill_package(pkg)

    def test_mock_output_contains_input(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.extract_keywords.v1")
        result = run_skill_package(
            pkg,
            {"text": "ai agents are transforming software engineering"},
            llm_provider=EchoLLMProvider(prefix=""),
        )
        # Mock echoes the prompt, which contains the input text
        assert "ai agents" in result.outputs["keywords"]
        assert "keywords" in result.outputs


# ── text.join_lines.v1 skill ─────────────────────────────────────────


class TestJoinLinesSkill:
    def test_validates(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.join_lines.v1")
        validate_skill_package(pkg)

    def test_formats_with_prefix(self) -> None:
        pkg = load_skill_package(EXAMPLE_DIR / "text.join_lines.v1")
        result = run_skill_package(
            pkg,
            {"lines": "AI agents, software, automation"},
        )
        assert result.outputs["joined"] == "Keywords:\nAI agents, software, automation"


# ── flagship multi-skill workflow ────────────────────────────────────


class TestFlagshipWorkflow:
    """Normalize → Extract Keywords → Join Lines."""

    @pytest.fixture()
    def reg(self, tmp_path: Path) -> LocalRegistry:
        r = LocalRegistry(root=tmp_path / "reg")
        r.publish(EXAMPLE_DIR / "text.normalize.v1")
        r.publish(EXAMPLE_DIR / "text.extract_keywords.v1")
        r.publish(EXAMPLE_DIR / "text.join_lines.v1")
        return r

    def test_normalize_then_extract_then_format(self, reg: LocalRegistry) -> None:
        glue = GlueGraph(
            goal="normalize, extract keywords, format",
            inputs=[IOField(name="text", type="string")],
            outputs=[IOField(name="result", type="string")],
            effects=["llm_inference"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(id="norm", op="skill.invoke",
                              config={"skill_id": "text.normalize.v1", "version": "1.0.0"}),
                    GraphNode(id="kw", op="skill.invoke",
                              config={"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}),
                    GraphNode(id="fmt", op="skill.invoke",
                              config={"skill_id": "text.join_lines.v1", "version": "1.0.0"}),
                ],
                edges=[
                    GraphEdge(from_="input.text", to="norm.text"),
                    GraphEdge(from_="norm.normalized", to="kw.text"),
                    GraphEdge(from_="kw.keywords", to="fmt.lines"),
                ],
                outputs={"result": "fmt.joined"},
            ),
        )

        result = run_glue_graph(
            glue,
            {"text": "  AI   agents ARE transforming SOFTWARE engineering  "},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=reg,
        )

        assert result.trace.status == "ok"
        output = result.outputs["result"]
        # Step 1 normalized: "ai agents are transforming software engineering"
        assert "ai agents are transforming software engineering" in output
        # Step 3 added prefix
        assert output.startswith("Keywords:\n")
        # 3 nodes executed
        assert len(result.trace.nodes) == 3

    def test_two_step_normalize_extract(self, reg: LocalRegistry) -> None:
        """Simpler two-step: normalize → extract keywords."""
        glue = GlueGraph(
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

        result = run_glue_graph(
            glue,
            {"text": "  AI   agents  "},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=reg,
        )
        assert result.trace.status == "ok"
        # Normalized text flows through to keyword extraction
        assert "ai agents" in result.outputs["keywords"]
