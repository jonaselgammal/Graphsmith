"""Tests for Sprint 37: explicit formatting intent + header constants."""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import build_planning_context
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.validator import validate_skill_package
from graphsmith.exceptions import ValidationError


class TestPromptCompositionPolicy:
    def test_has_composition_policy(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "COMPOSITION POLICY" in ctx

    def test_must_add_formatting_when_asked(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "you MUST" in ctx
        assert "formatting" in ctx.lower()

    def test_shows_2_node_format_example(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "2 nodes (extract + join_lines)" in ctx

    def test_shows_header_example(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "2 nodes (extract + template.render)" in ctx


class TestPromptConstantsRule:
    def test_lists_invalid_pseudo_inputs(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "input.prefix_const" in ctx
        assert "input.header" in ctx

    def test_shows_valid_template_render(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "Results:" in ctx and "{{text}}" in ctx


class TestExplicitFormatComposition:
    """'format as a list' must include formatting node."""

    def test_correct_2_node_format_plan(self) -> None:
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
        result = parse_planner_output(json.dumps(plan), goal="format as list")
        assert result.status == "success"
        assert len(result.graph.graph.nodes) == 2
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)


class TestHeaderConstantHandling:
    """'add a header saying Results' must use config, not graph input."""

    def test_correct_header_via_template(self) -> None:
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
        result = parse_planner_output(json.dumps(plan), goal="add header Results")
        assert result.status == "success"
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)

    def test_invalid_prefix_const_input_fails(self) -> None:
        """input.prefix_const is not a declared input → validation failure."""
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "prefixed", "type": "string"}],
            "nodes": [
                {"id": "extract", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
                {"id": "prefix", "op": "skill.invoke",
                 "config": {"skill_id": "text.prefix_lines.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "extract.text"},
                {"from": "extract.keywords", "to": "prefix.text"},
                {"from": "input.prefix_const", "to": "prefix.prefix"},
            ],
            "graph_outputs": {"prefixed": "prefix.prefixed"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError, match="prefix_const"):
            validate_skill_package(pkg)


class TestPlainExtractionRegression:
    """Plain extraction must NOT add formatting."""

    def test_single_node_keywords(self) -> None:
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
        result = parse_planner_output(json.dumps(plan), goal="extract keywords")
        assert result.status == "success"
        assert len(result.graph.graph.nodes) == 1
