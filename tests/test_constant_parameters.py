"""Tests for Sprint 24: constant/literal parameter handling."""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import PROMPT_VERSION, build_planning_context
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.validator import validate_skill_package


# ── prompt content ───────────────────────────────────────────────────


class TestPromptConstantGuidance:
    def test_version_v7(self) -> None:
        assert PROMPT_VERSION == "v7"

    def test_has_constant_vs_input_rule(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "CONSTANTS vs INPUTS" in ctx or "CONSTANT" in ctx

    def test_mentions_template_render_for_constants(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "config.template" in ctx

    def test_has_constant_header_example(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "Results:" in ctx
        assert "constant" in ctx.lower()

    def test_example3b_uses_template_render(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert '"op": "template.render"' in ctx
        assert "Results:" in ctx
        assert "{{text}}" in ctx


# ── correct constant-header plan ─────────────────────────────────────


class TestConstantHeaderPlan:
    """The exact pattern the planner should produce for "add a header saying X"."""

    def test_extract_then_format_with_constant(self) -> None:
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
        assert result.graph is not None
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)  # should not raise

    def test_bullet_list_with_join_lines(self) -> None:
        """'Make a bullet list' should use text.join_lines.v1 (header baked in)."""
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


# ── broken pattern: graph input for a constant ───────────────────────


class TestBrokenConstantAsInput:
    """The pattern the LLM was producing — should fail validation."""

    def test_undeclared_prefix_input_fails(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "prefixed", "type": "string"}],
            "nodes": [
                {"id": "extract", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
                {"id": "format", "op": "skill.invoke",
                 "config": {"skill_id": "text.prefix_lines.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "extract.text"},
                {"from": "extract.keywords", "to": "format.text"},
                {"from": "input.prefix_header", "to": "format.prefix"},
            ],
            "graph_outputs": {"prefixed": "format.prefixed"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"  # parser doesn't check this
        pkg = glue_to_skill_package(result.graph)
        from graphsmith.exceptions import ValidationError
        with pytest.raises(ValidationError, match="prefix_header"):
            validate_skill_package(pkg)


# ── no regression ────────────────────────────────────────────────────


class TestNoRegression:
    def test_normal_formatting_chain(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "joined", "type": "string"}],
            "nodes": [
                {"id": "kw", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
                {"id": "fmt", "op": "skill.invoke",
                 "config": {"skill_id": "text.join_lines.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "kw.text"},
                {"from": "kw.keywords", "to": "fmt.lines"},
            ],
            "graph_outputs": {"joined": "fmt.joined"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)

    def test_normalize_and_extract(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [
                {"name": "normalized", "type": "string"},
                {"name": "keywords", "type": "string"},
            ],
            "nodes": [
                {"id": "n", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
                {"id": "k", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "n.text"},
                {"from": "n.normalized", "to": "k.text"},
            ],
            "graph_outputs": {
                "normalized": "n.normalized",
                "keywords": "k.keywords",
            },
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
