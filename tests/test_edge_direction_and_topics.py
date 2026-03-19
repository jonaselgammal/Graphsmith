"""Tests for Sprint 38: edge direction, self-loops, and topic output."""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import build_planning_context
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.validator import validate_skill_package
from graphsmith.exceptions import ValidationError


class TestPromptTopicNoFormat:
    def test_find_topics_listed_as_no_format(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "Find the key topics" in ctx

    def test_find_topics_is_1_node(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        # Both should be listed as 1-node cases
        assert "1 node (extract only)" in ctx


class TestPromptSelfLoopProhibition:
    def test_has_self_loop_rule(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "SELF-LOOP" in ctx or "self-loop" in ctx.lower()

    def test_mentions_format_prefix_example(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "format.prefix" in ctx


class TestSelfLoopValidation:
    def test_self_loop_creates_cycle(self) -> None:
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
                {"from": "format.prefix", "to": "format.prefix"},
            ],
            "graph_outputs": {"prefixed": "format.prefixed"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError, match="cycle"):
            validate_skill_package(pkg)


class TestCorrectHeaderPlan:
    def test_header_via_template_render(self) -> None:
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
        assert len(result.graph.graph.nodes) == 2
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)


class TestPlainTopicExtraction:
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
        result = parse_planner_output(json.dumps(plan), goal="find topics")
        assert result.status == "success"
        assert len(result.graph.graph.nodes) == 1
        assert "keywords" in result.graph.graph.outputs


class TestExplicitFormatStillWorks:
    def test_format_as_list_has_2_nodes(self) -> None:
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
