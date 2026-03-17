"""Regression tests for type grammar alignment (Sprint 10B).

Covers the real-world failure where an LLM emitted bare "array"
instead of "array<string>" in a planned glue graph.
"""
from __future__ import annotations

import json

import pytest

from graphsmith.exceptions import ValidationError
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import build_planning_context, PROMPT_VERSION
from graphsmith.planner.models import PlanRequest
from graphsmith.validator import validate_skill_package


def _plan_with_type(output_type: str) -> str:
    """Return a planner JSON output where keywords has the given type."""
    return json.dumps({
        "inputs": [{"name": "text", "type": "string"}],
        "outputs": [
            {"name": "normalized", "type": "string"},
            {"name": "keywords", "type": output_type},
        ],
        "nodes": [
            {
                "id": "normalize",
                "op": "skill.invoke",
                "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"},
            },
            {
                "id": "extract_keywords",
                "op": "skill.invoke",
                "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"},
            },
        ],
        "edges": [
            {"from": "input.text", "to": "normalize.text"},
            {"from": "normalize.normalized", "to": "extract_keywords.text"},
        ],
        "graph_outputs": {
            "normalized": "normalize.normalized",
            "keywords": "extract_keywords.keywords",
        },
        "effects": ["llm_inference"],
    })


class TestBareArrayRejection:
    """Regression: LLM emitted bare 'array' — must fail with actionable error."""

    def test_bare_array_parses_but_validation_fails(self) -> None:
        """Parser succeeds (it doesn't validate types), but
        validation rejects bare 'array' with an actionable message."""
        raw = _plan_with_type("array")
        result = parse_planner_output(raw, goal="test")
        # Parser succeeds — it builds the GlueGraph structurally
        assert result.status == "success"
        assert result.graph is not None

        # But validation catches the bare 'array'
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError) as exc_info:
            validate_skill_package(pkg)
        msg = str(exc_info.value)
        assert "array" in msg
        assert "array<string>" in msg  # actionable suggestion
        assert "keywords" in msg

    def test_compose_plan_demotes_to_partial(self) -> None:
        """Through compose_plan, bare 'array' results in partial status."""
        from graphsmith.planner.composer import _validate_glue_graph
        from graphsmith.planner.models import PlanResult

        raw = _plan_with_type("array")
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"

        validated = _validate_glue_graph(result)
        assert validated.status == "partial"
        assert any(h.kind == "validation_error" for h in validated.holes)
        assert any("array<string>" in h.description for h in validated.holes)


class TestArrayStringAccepted:
    """Positive test: array<string> passes validation."""

    def test_array_string_validates(self) -> None:
        raw = _plan_with_type("array<string>")
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"
        assert result.graph is not None

        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)  # should not raise

    def test_optional_string_validates(self) -> None:
        raw = _plan_with_type("optional<string>")
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)

    def test_array_object_validates(self) -> None:
        raw = _plan_with_type("array<object>")
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)


class TestBareOptionalRejection:
    """Same pattern: bare 'optional' should fail with a hint."""

    def test_bare_optional_fails_with_hint(self) -> None:
        raw = _plan_with_type("optional")
        result = parse_planner_output(raw, goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError) as exc_info:
            validate_skill_package(pkg)
        msg = str(exc_info.value)
        assert "optional<string>" in msg


class TestPromptContainsTypeGrammar:
    """The prompt must teach the LLM about parameterised types."""

    def test_prompt_mentions_array_string(self) -> None:
        req = PlanRequest(goal="test", candidates=[])
        ctx = build_planning_context(req)
        assert "array<string>" in ctx

    def test_prompt_has_allowed_types_section(self) -> None:
        req = PlanRequest(goal="test", candidates=[])
        ctx = build_planning_context(req)
        assert "Allowed types" in ctx
        assert "array<string>" in ctx

    def test_prompt_lists_base_types(self) -> None:
        req = PlanRequest(goal="test", candidates=[])
        ctx = build_planning_context(req)
        for t in ("string", "integer", "number", "boolean", "object"):
            assert t in ctx

    def test_prompt_lists_array_type(self) -> None:
        req = PlanRequest(goal="test", candidates=[])
        ctx = build_planning_context(req)
        assert "array<string>" in ctx
