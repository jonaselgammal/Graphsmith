"""Tests for Sprint 36: final challenge case — multi-step paraphrase composition."""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import build_planning_context
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.validator import validate_skill_package


class TestPromptMultiStepParaphrase:
    def test_prompt_mentions_3_step_paraphrase(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "3 steps" in ctx

    def test_prompt_says_do_not_skip_normalize(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "Do NOT skip" in ctx


class TestCleanExtractFormatComposition:
    """The exact failing challenge pattern: clean + extract + format = 3 nodes."""

    def test_correct_3_node_plan(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "prefixed", "type": "string"}],
            "nodes": [
                {"id": "normalize", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
                {"id": "extract", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
                {"id": "format", "op": "template.render",
                 "config": {"template": "Key Topics:\n{{text}}"}},
            ],
            "edges": [
                {"from": "input.text", "to": "normalize.text"},
                {"from": "normalize.normalized", "to": "extract.text"},
                {"from": "extract.keywords", "to": "format.text"},
            ],
            "graph_outputs": {"prefixed": "format.rendered"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="clean up and format")
        assert result.status == "success"
        assert len(result.graph.graph.nodes) == 3
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)

    def test_missing_normalize_has_only_2_nodes(self) -> None:
        """The broken pattern: skips normalize, only has extract + format."""
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
                {"from": "input.text", "to": "prefix.prefix"},
            ],
            "graph_outputs": {"prefixed": "prefix.prefixed"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        # Only 2 nodes — missing normalize
        assert len(result.graph.graph.nodes) == 2


class TestPlainExtractionNotOverComposed:
    """Regression: plain extraction must NOT add formatting."""

    def test_single_skill_extraction(self) -> None:
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
