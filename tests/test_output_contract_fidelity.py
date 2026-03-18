"""Tests for Sprint 30: output contract fidelity."""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import build_planning_context
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.validator import validate_skill_package


# ── prompt content ───────────────────────────────────────────────────


class TestPromptContractFidelity:
    def test_has_output_ports_label(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "output_ports" in ctx or "port name" in ctx.lower()

    def test_has_json_example(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "json.reshape.v1" in ctx
        assert '"selected"' in ctx

    def test_warns_against_splitting_outputs(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "NEVER split" in ctx or "NEVER invent" in ctx

    def test_shows_name_and_value_example(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        lower = ctx.lower()
        assert "name and value" in lower


# ── topics → keywords fidelity ───────────────────────────────────────


class TestTopicsKeywordsFidelity:
    def test_correct_plan_uses_keywords(self) -> None:
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
        result = parse_planner_output(json.dumps(plan), goal="find key topics")
        assert result.status == "success"
        assert "keywords" in result.graph.graph.outputs
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)


# ── JSON extraction fidelity ─────────────────────────────────────────


class TestJsonExtractionFidelity:
    def test_reshape_with_selected_output(self) -> None:
        plan = {
            "inputs": [{"name": "raw_json", "type": "string"}],
            "outputs": [{"name": "selected", "type": "object"}],
            "nodes": [
                {"id": "reshape", "op": "skill.invoke",
                 "config": {"skill_id": "json.reshape.v1", "version": "1.0.0"}},
            ],
            "edges": [{"from": "input.raw_json", "to": "reshape.raw_json"}],
            "graph_outputs": {"selected": "reshape.selected"},
        }
        result = parse_planner_output(json.dumps(plan), goal="extract name and value")
        assert result.status == "success"
        assert "selected" in result.graph.graph.outputs
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)

    def test_wrong_split_outputs_still_valid_if_mapped(self) -> None:
        """Even if LLM splits into name+value, it should validate if mapped."""
        plan = {
            "inputs": [{"name": "raw_json", "type": "string"}],
            "outputs": [{"name": "value", "type": "string"}],
            "nodes": [
                {"id": "extract", "op": "skill.invoke",
                 "config": {"skill_id": "json.extract_field.v1", "version": "1.0.0"}},
            ],
            "edges": [{"from": "input.raw_json", "to": "extract.raw_json"}],
            "graph_outputs": {"value": "extract.value"},
        }
        result = parse_planner_output(json.dumps(plan), goal="extract value")
        assert result.status == "success"


# ── no regression ────────────────────────────────────────────────────


class TestNoRegression:
    def test_normalize_extract_still_works(self) -> None:
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
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
