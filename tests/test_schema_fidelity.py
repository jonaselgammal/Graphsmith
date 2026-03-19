"""Tests for Sprint 34: schema fidelity — address syntax, effects, edge conflicts."""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import build_planning_context
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.validator import validate_skill_package
from graphsmith.exceptions import ValidationError


class TestPromptSchemaRules:
    def test_prohibits_output_scope(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert '"output" is NOT a valid scope' in ctx

    def test_prohibits_bare_addresses(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "bare words" in ctx.lower() or "INVALID" in ctx

    def test_lists_allowed_effects(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "pure, llm_inference" in ctx

    def test_prohibits_invented_effects(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "Do NOT invent effects" in ctx

    def test_prohibits_edge_conflicts(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "ONE source edge" in ctx

    def test_graph_outputs_must_ref_real_nodes(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "actual node ID" in ctx


class TestOutputScopeRejection:
    """Plans using 'output.X' as edge destination must fail validation."""

    def test_output_dest_fails(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "summary", "type": "string"}],
            "nodes": [
                {"id": "s", "op": "skill.invoke",
                 "config": {"skill_id": "text.summarize.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "s.text"},
                {"from": "s.summary", "to": "output.summary"},
            ],
            "graph_outputs": {"summary": "s.summary"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.graph is not None
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError):
            validate_skill_package(pkg)


class TestInventedEffectRejection:
    def test_text_normalization_effect_fails(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "normalized", "type": "string"}],
            "nodes": [
                {"id": "n", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
            ],
            "edges": [{"from": "input.text", "to": "n.text"}],
            "graph_outputs": {"normalized": "n.normalized"},
            "effects": ["text_normalization"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError, match="text_normalization"):
            validate_skill_package(pkg)


class TestWrongNodeIdInOutputs:
    def test_mismatched_node_id_fails(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "count", "type": "string"}],
            "nodes": [
                {"id": "count_text", "op": "skill.invoke",
                 "config": {"skill_id": "text.word_count.v1", "version": "1.0.0"}},
            ],
            "edges": [{"from": "input.text", "to": "count_text.text"}],
            "graph_outputs": {"count": "count.count"},
            "effects": ["pure"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError):
            validate_skill_package(pkg)


class TestCorrectPlansStillPass:
    def test_simple_normalize(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "normalized", "type": "string"}],
            "nodes": [
                {"id": "n", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
            ],
            "edges": [{"from": "input.text", "to": "n.text"}],
            "graph_outputs": {"normalized": "n.normalized"},
            "effects": ["pure"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)

    def test_multi_skill_chain(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "keywords", "type": "string"}],
            "nodes": [
                {"id": "norm", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
                {"id": "kw", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "norm.text"},
                {"from": "norm.normalized", "to": "kw.text"},
            ],
            "graph_outputs": {"keywords": "kw.keywords"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)
