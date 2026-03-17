"""Regression tests for optional input semantics (Sprint 10H).

Covers the real-world failure where text.summarize.v1 crashed when
invoked without the optional max_sentences input.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from graphsmith.exceptions import ExecutionError
from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.parser import load_skill_package
from graphsmith.registry import LocalRegistry
from graphsmith.runtime import run_skill_package
from graphsmith.planner import run_glue_graph
from graphsmith.planner.models import GlueGraph
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.validator import validate_skill_package

from conftest import EXAMPLE_DIR, minimal_examples, minimal_graph, minimal_skill, write_package


# ── text.summarize.v1 with and without max_sentences ─────────────────


class TestSummarizeOptionalInput:
    def test_with_both_inputs(self) -> None:
        """text.summarize.v1 works when both text and max_sentences are provided."""
        pkg = load_skill_package(EXAMPLE_DIR / "text.summarize.v1")
        validate_skill_package(pkg)
        result = run_skill_package(
            pkg,
            {"text": "Cats sleep a lot", "max_sentences": 2},
            llm_provider=EchoLLMProvider(prefix=""),
        )
        assert result.trace.status == "ok"
        assert "Cats sleep a lot" in result.outputs["summary"]
        assert "2" in result.outputs["summary"]

    def test_with_only_text(self) -> None:
        """text.summarize.v1 works when optional max_sentences is omitted."""
        pkg = load_skill_package(EXAMPLE_DIR / "text.summarize.v1")
        validate_skill_package(pkg)
        result = run_skill_package(
            pkg,
            {"text": "Cats sleep a lot"},
            llm_provider=EchoLLMProvider(prefix=""),
        )
        assert result.trace.status == "ok"
        assert "Cats sleep a lot" in result.outputs["summary"]

    def test_missing_required_text_still_fails(self) -> None:
        """Omitting the required 'text' input still fails."""
        pkg = load_skill_package(EXAMPLE_DIR / "text.summarize.v1")
        validate_skill_package(pkg)
        with pytest.raises(ExecutionError, match="not provided"):
            run_skill_package(
                pkg,
                {},  # missing required 'text'
                llm_provider=EchoLLMProvider(prefix=""),
            )


# ── skill.invoke with optional inputs ────────────────────────────────


class TestSkillInvokeOptional:
    def test_invoke_summarize_without_optional(self, tmp_path: Path) -> None:
        """Glue graph invokes text.summarize.v1 without max_sentences."""
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")

        glue = GlueGraph(
            goal="summarize",
            inputs=[IOField(name="text", type="string")],
            outputs=[IOField(name="summary", type="string")],
            effects=["llm_inference"],
            graph=GraphBody(
                version=1,
                nodes=[GraphNode(
                    id="call", op="skill.invoke",
                    config={"skill_id": "text.summarize.v1", "version": "1.0.0"},
                )],
                edges=[GraphEdge(from_="input.text", to="call.text")],
                outputs={"summary": "call.summary"},
            ),
        )

        result = run_glue_graph(
            glue,
            {"text": "Cats sleep a lot"},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=reg,
        )
        assert result.trace.status == "ok"
        assert "summary" in result.outputs


# ── template.render with missing variables ───────────────────────────


class TestTemplateRenderMissing:
    def test_missing_var_renders_empty(self) -> None:
        """template.render renders absent variables as empty string."""
        from graphsmith.ops.template import template_render
        result = template_render(
            {"template": "Hello {{name}}, you have {{count}} items"},
            {"name": "Alice"},  # count is absent
        )
        assert result["rendered"] == "Hello Alice, you have  items"

    def test_all_vars_present(self) -> None:
        from graphsmith.ops.template import template_render
        result = template_render(
            {"template": "{{a}} and {{b}}"},
            {"a": "X", "b": "Y"},
        )
        assert result["rendered"] == "X and Y"


# ── required inputs remain strict ────────────────────────────────────


class TestRequiredInputsStillStrict:
    def test_required_missing_fails(self, tmp_path: Path) -> None:
        write_package(
            tmp_path / "pkg",
            skill=minimal_skill(),
            graph=minimal_graph(),
            examples=minimal_examples(),
        )
        pkg = load_skill_package(tmp_path / "pkg")
        validate_skill_package(pkg)
        with pytest.raises(ExecutionError, match="not provided"):
            run_skill_package(pkg, {})

    def test_required_provided_succeeds(self, tmp_path: Path) -> None:
        write_package(
            tmp_path / "pkg",
            skill=minimal_skill(),
            graph=minimal_graph(),
            examples=minimal_examples(),
        )
        pkg = load_skill_package(tmp_path / "pkg")
        validate_skill_package(pkg)
        result = run_skill_package(pkg, {"text": "hello"})
        assert result.trace.status == "ok"
