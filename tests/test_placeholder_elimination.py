"""Regression tests for placeholder-token elimination (Sprint 10E).

Covers the real-world failure where the LLM copied placeholder tokens
like NAME and TYPE literally from the prompt template.
"""
from __future__ import annotations

import json

import pytest

from graphsmith.exceptions import ValidationError
from graphsmith.planner.composer import _validate_glue_graph, glue_to_skill_package
from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import PROMPT_VERSION, build_planning_context
from graphsmith.validator import validate_skill_package


def _plan_json(**field_overrides: str) -> str:
    """Build planner output with optional field value overrides."""
    data = {
        "inputs": [{"name": field_overrides.get("input_name", "text"),
                     "type": field_overrides.get("input_type", "string")}],
        "outputs": [{"name": field_overrides.get("output_name", "result"),
                      "type": field_overrides.get("output_type", "string")}],
        "nodes": [{"id": "s", "op": "template.render",
                   "config": {"template": "{{text}}"}}],
        "edges": [{"from": "input.text", "to": "s.text"}],
        "graph_outputs": {"result": "s.rendered"},
    }
    return json.dumps(data)


# ── placeholder-token regression ─────────────────────────────────────


class TestPlaceholderTypeRejection:
    """LLM copied TYPE/NAME from prompt template as literal values."""

    def test_literal_TYPE_rejected(self) -> None:
        raw = _plan_json(output_type="TYPE")
        result = parse_planner_output(raw, goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError) as exc_info:
            validate_skill_package(pkg)
        msg = str(exc_info.value)
        assert "placeholder" in msg.lower()
        assert "TYPE" in msg

    def test_literal_NAME_as_type_rejected(self) -> None:
        raw = _plan_json(output_type="NAME")
        result = parse_planner_output(raw, goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError, match="placeholder"):
            validate_skill_package(pkg)

    def test_literal_STR_rejected(self) -> None:
        raw = _plan_json(output_type="STR")
        result = parse_planner_output(raw, goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError, match="placeholder"):
            validate_skill_package(pkg)

    def test_lowercase_type_rejected(self) -> None:
        """Even lowercase 'type' should be caught."""
        raw = _plan_json(output_type="type")
        result = parse_planner_output(raw, goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError, match="placeholder"):
            validate_skill_package(pkg)

    def test_compose_demotes_to_partial(self) -> None:
        raw = _plan_json(output_type="TYPE", output_name="NAME")
        result = parse_planner_output(raw, goal="test")
        validated = _validate_glue_graph(result)
        assert validated.status == "partial"
        assert any("placeholder" in h.description.lower() for h in validated.holes)


# ── prompt no longer has abstract placeholders ───────────────────────


class TestPromptNoPlaceholders:
    def test_no_NAME_placeholder(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        # NAME should not appear as a JSON value in the output section
        assert '"NAME"' not in ctx

    def test_no_TYPE_placeholder(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert '"TYPE"' not in ctx

    def test_no_NODE_ID_placeholder(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert '"NODE_ID"' not in ctx

    def test_no_OP_NAME_placeholder(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert '"OP_NAME"' not in ctx

    def test_prompt_version_v4(self) -> None:
        assert PROMPT_VERSION == "v6"

    def test_prompt_has_concrete_examples(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        # Should have real field names from concrete examples
        assert '"text"' in ctx
        assert '"summary"' in ctx
        assert '"string"' in ctx

    def test_prompt_has_multi_skill_example(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "normalize" in ctx
        assert "extract" in ctx

    def test_prompt_says_no_placeholders(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "placeholder" in ctx.lower()


# ── positive: real types still work ──────────────────────────────────


class TestRealTypesStillWork:
    @pytest.mark.parametrize("t", [
        "string", "integer", "number", "boolean", "object",
        "array<string>", "optional<integer>",
    ])
    def test_valid_type(self, t: str) -> None:
        raw = _plan_json(output_type=t)
        result = parse_planner_output(raw, goal="test")
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)  # should not raise
