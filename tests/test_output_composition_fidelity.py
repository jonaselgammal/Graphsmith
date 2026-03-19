"""Tests for Sprint 35: output semantics + composition discipline."""
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

    def test_says_no_formatting_unless_asked(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "do NOT add formatting" in ctx.lower() or "do NOT add formatting" in ctx

    def test_shows_keywords_only_example(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "1 node (extract only)" in ctx


class TestSingleSkillKeywordExtraction:
    """'Extract keywords' should NOT add formatting nodes."""

    def test_correct_single_skill_plan(self) -> None:
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
        assert "keywords" in result.graph.graph.outputs

    def test_over_composed_plan_has_wrong_output(self) -> None:
        """The broken pattern: adds join_lines and exposes 'joined' not 'keywords'."""
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
        result = parse_planner_output(json.dumps(plan), goal="extract keywords")
        # This plan is structurally valid but semantically wrong —
        # "keywords" is not in graph_outputs
        assert "keywords" not in result.graph.graph.outputs


class TestUndeclaredOutputRejection:
    def test_undeclared_graph_output_fails(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "normalized", "type": "string"}],
            "nodes": [
                {"id": "n", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
            ],
            "edges": [{"from": "input.text", "to": "n.text"}],
            "graph_outputs": {
                "normalized": "n.normalized",
                "clean_text": "n.normalized",
            },
            "effects": ["pure"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError, match="clean_text"):
            validate_skill_package(pkg)


class TestMultiSourceRejection:
    def test_two_sources_to_one_port_fails(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "keywords", "type": "string"}],
            "nodes": [
                {"id": "norm", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
                {"id": "sum", "op": "skill.invoke",
                 "config": {"skill_id": "text.summarize.v1", "version": "1.0.0"}},
                {"id": "kw", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "norm.text"},
                {"from": "norm.normalized", "to": "sum.text"},
                {"from": "sum.summary", "to": "kw.text"},
                {"from": "norm.normalized", "to": "kw.text"},
            ],
            "graph_outputs": {"keywords": "kw.keywords"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError, match="Conflicting"):
            validate_skill_package(pkg)


class TestSelfLoopRejection:
    def test_self_loop_fails(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "keywords", "type": "string"}],
            "nodes": [
                {"id": "extract", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
                {"id": "format", "op": "skill.invoke",
                 "config": {"skill_id": "text.join_lines.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "extract.text"},
                {"from": "format.lines", "to": "format.lines"},
            ],
            "graph_outputs": {"keywords": "extract.keywords"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError):
            validate_skill_package(pkg)
