"""Regression tests for real-world LLM type failures (Sprint 10D).

Covers the case where the LLM copies prompt placeholders like <str>
as literal type values.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphsmith.exceptions import ValidationError
from graphsmith.planner.composer import _validate_glue_graph, glue_to_skill_package
from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import build_planning_context
from graphsmith.validator import validate_skill_package


def _plan_with_types(**type_overrides: str) -> str:
    """Build a planner JSON output with custom type values."""
    data = {
        "inputs": [{"name": "text", "type": type_overrides.get("input_type", "string")}],
        "outputs": [{"name": "result", "type": type_overrides.get("output_type", "string")}],
        "nodes": [{"id": "s", "op": "template.render", "config": {"template": "{{text}}"}}],
        "edges": [{"from": "input.text", "to": "s.text"}],
        "graph_outputs": {"result": "s.rendered"},
    }
    return json.dumps(data)


# ── <str> literal regression ─────────────────────────────────────────


class TestAngleBracketStr:
    """The LLM copied '<str>' from a prompt placeholder as a literal type."""

    def test_angle_str_parses_but_validation_fails(self) -> None:
        raw = _plan_with_types(output_type="<str>")
        result = parse_planner_output(raw, goal="test")
        # Parser succeeds structurally
        assert result.status == "success"
        assert result.graph is not None

        # Validator catches it
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError) as exc_info:
            validate_skill_package(pkg)
        msg = str(exc_info.value)
        assert "<str>" in msg
        assert "not a valid type" in msg.lower() or "Malformed" in msg

    def test_angle_str_in_input(self) -> None:
        raw = _plan_with_types(input_type="<str>")
        result = parse_planner_output(raw, goal="test")
        assert result.graph is not None
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError, match="<str>"):
            validate_skill_package(pkg)

    def test_compose_demotes_to_partial(self) -> None:
        raw = _plan_with_types(output_type="<str>")
        result = parse_planner_output(raw, goal="test")
        validated = _validate_glue_graph(result)
        assert validated.status == "partial"
        assert any(h.kind == "validation_error" for h in validated.holes)


# ── other LLM type mistakes ──────────────────────────────────────────


class TestOtherMalformedTypes:
    def test_python_str_rejected(self) -> None:
        raw = _plan_with_types(output_type="str")
        result = parse_planner_output(raw, goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError, match="str"):
            validate_skill_package(pkg)

    def test_python_list_rejected(self) -> None:
        raw = _plan_with_types(output_type="list")
        result = parse_planner_output(raw, goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError, match="list"):
            validate_skill_package(pkg)

    def test_angle_name_rejected(self) -> None:
        """<name> as a type is rejected."""
        raw = _plan_with_types(output_type="<name>")
        result = parse_planner_output(raw, goal="test")
        pkg = glue_to_skill_package(result.graph)
        with pytest.raises(ValidationError):
            validate_skill_package(pkg)


# ── prompt no longer has angle-bracket placeholders ──────────────────


class TestPromptNoAngleBrackets:
    def test_no_angle_str_in_schema(self) -> None:
        req = PlanRequest(goal="test", candidates=[])
        ctx = build_planning_context(req)
        # The schema template should NOT contain <str>
        assert '"<str>"' not in ctx

    def test_no_angle_name_in_schema(self) -> None:
        req = PlanRequest(goal="test", candidates=[])
        ctx = build_planning_context(req)
        assert '"<name>"' not in ctx

    def test_no_caps_placeholders_in_prompt(self) -> None:
        """v2 prompt uses only concrete examples, no abstract placeholders."""
        req = PlanRequest(goal="test", candidates=[])
        ctx = build_planning_context(req)
        assert '"NAME"' not in ctx
        assert '"TYPE"' not in ctx
        assert '"NODE_ID"' not in ctx

    def test_has_concrete_type_examples(self) -> None:
        req = PlanRequest(goal="test", candidates=[])
        ctx = build_planning_context(req)
        assert '"string"' in ctx
        assert "integer" in ctx
        assert "array<string>" in ctx


# ── positive cases still work ────────────────────────────────────────


class TestValidTypesStillWork:
    @pytest.mark.parametrize("type_str", [
        "string", "integer", "number", "boolean", "object",
        "array<string>", "optional<integer>", "array<object>",
    ])
    def test_valid_type_passes(self, type_str: str) -> None:
        raw = _plan_with_types(output_type=type_str)
        result = parse_planner_output(raw, goal="test")
        assert result.graph is not None
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)  # should not raise


# ── CLI --save-on-failure ────────────────────────────────────────────


class TestSaveOnFailure:
    def test_plan_save_on_failure(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()

        debug_path = tmp_path / "debug.json"
        # Empty registry → plan fails
        result = runner.invoke(app, [
            "plan", "test",
            "--registry", str(tmp_path / "reg"),
            "--save-on-failure", str(debug_path),
        ])
        assert result.exit_code == 1
        assert debug_path.exists()
        data = json.loads(debug_path.read_text())
        assert data["status"] == "failure"

    def test_plan_and_run_save_on_failure(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()

        debug_path = tmp_path / "debug.json"
        result = runner.invoke(app, [
            "plan-and-run", "test",
            "--registry", str(tmp_path / "reg"),
            "--save-on-failure", str(debug_path),
        ])
        assert result.exit_code == 1
        assert debug_path.exists()
