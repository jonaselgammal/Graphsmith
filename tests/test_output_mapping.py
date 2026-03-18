"""Regression tests for output mapping completeness (Sprint 10F).

Covers the real-world failure where the LLM declared an output
but omitted it from graph_outputs.
"""
from __future__ import annotations

import json

import pytest

from graphsmith.exceptions import ValidationError
from graphsmith.planner.composer import _validate_glue_graph, glue_to_skill_package
from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import build_planning_context
from graphsmith.validator import validate_skill_package


def _plan_json(*, outputs: list[dict], graph_outputs: dict) -> str:
    return json.dumps({
        "inputs": [{"name": "text", "type": "string"}],
        "outputs": outputs,
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
        "graph_outputs": graph_outputs,
        "effects": ["llm_inference"],
    })


class TestMissingOutputMapping:
    """LLM declared output 'keywords' but omitted it from graph_outputs."""

    def test_missing_mapping_fails_validation(self) -> None:
        raw = _plan_json(
            outputs=[
                {"name": "normalized", "type": "string"},
                {"name": "keywords", "type": "string"},
            ],
            graph_outputs={"normalized": "norm.normalized"},
            # keywords is missing from graph_outputs
        )
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"  # parser succeeds
        assert result.graph is not None

        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError) as exc_info:
            validate_skill_package(pkg)
        msg = str(exc_info.value)
        assert "keywords" in msg
        assert "graph_outputs" in msg

    def test_compose_demotes_to_partial(self) -> None:
        raw = _plan_json(
            outputs=[
                {"name": "normalized", "type": "string"},
                {"name": "keywords", "type": "string"},
            ],
            graph_outputs={"normalized": "norm.normalized"},
        )
        result = parse_planner_output(raw, goal="test")
        validated = _validate_glue_graph(result)
        assert validated.status == "partial"
        assert any("keywords" in h.description for h in validated.holes)

    def test_error_message_is_actionable(self) -> None:
        raw = _plan_json(
            outputs=[{"name": "result", "type": "string"}],
            graph_outputs={},
        )
        result = parse_planner_output(raw, goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError) as exc_info:
            validate_skill_package(pkg)
        msg = str(exc_info.value)
        assert "graph_outputs" in msg
        assert "node port" in msg


class TestCompleteOutputMapping:
    """Positive: all declared outputs are mapped."""

    def test_multi_output_complete(self) -> None:
        raw = _plan_json(
            outputs=[
                {"name": "normalized", "type": "string"},
                {"name": "keywords", "type": "string"},
            ],
            graph_outputs={
                "normalized": "norm.normalized",
                "keywords": "kw.keywords",
            },
        )
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)  # should not raise

    def test_single_output_complete(self) -> None:
        raw = _plan_json(
            outputs=[{"name": "keywords", "type": "string"}],
            graph_outputs={"keywords": "kw.keywords"},
        )
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)


class TestPromptCompletenessGuidance:
    def test_prompt_mentions_output_mapping_rule(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "graph_outputs" in ctx
        # Must mention that every output needs a mapping
        lower = ctx.lower()
        assert "every" in lower and "graph_outputs" in lower

    def test_example1_maps_all_outputs(self) -> None:
        """Example 1 must not have unmapped outputs."""
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert '"keywords": "extract.keywords"' in ctx
