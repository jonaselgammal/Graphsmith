"""Tests for planner output parsing."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.planner import (
    LLMPlannerBackend,
    compose_plan,
    parse_planner_output,
)
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.registry import LocalRegistry
from graphsmith.validator import validate_skill_package

from conftest import EXAMPLE_DIR


# ── helpers ──────────────────────────────────────────────────────────


def _valid_plan_json(**overrides: Any) -> str:
    """Return a valid JSON planner output string."""
    data = {
        "inputs": [{"name": "text", "type": "string"}],
        "outputs": [{"name": "result", "type": "string"}],
        "nodes": [
            {
                "id": "step",
                "op": "template.render",
                "config": {"template": "{{text}}"},
            }
        ],
        "edges": [{"from": "input.text", "to": "step.text"}],
        "graph_outputs": {"result": "step.rendered"},
    }
    data.update(overrides)
    return json.dumps(data)


class _CannedLLMProvider:
    """Test provider that returns a canned response."""

    def __init__(self, response: str) -> None:
        self._response = response

    def generate(self, prompt: str, **kwargs: Any) -> str:
        return self._response

    def extract(self, prompt: str, schema: dict, **kwargs: Any) -> dict:
        return {}


# ── valid output ─────────────────────────────────────────────────────


class TestValidOutput:
    def test_success(self) -> None:
        result = parse_planner_output(_valid_plan_json(), goal="test")
        assert result.status == "success"
        assert result.graph is not None
        assert result.graph.goal == "test"
        assert len(result.graph.inputs) == 1
        assert len(result.graph.outputs) == 1
        assert len(result.graph.graph.nodes) == 1
        assert result.holes == []

    def test_success_with_effects(self) -> None:
        raw = _valid_plan_json(effects=["llm_inference"])
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"
        assert result.graph is not None
        assert result.graph.effects == ["llm_inference"]

    def test_default_effects(self) -> None:
        result = parse_planner_output(_valid_plan_json(), goal="test")
        assert result.graph is not None
        assert result.graph.effects == ["pure"]

    def test_with_reasoning(self) -> None:
        raw = _valid_plan_json(reasoning="Used template op.")
        result = parse_planner_output(raw, goal="test")
        assert result.reasoning == "Used template op."

    def test_multi_node_graph(self) -> None:
        data = {
            "inputs": [
                {"name": "text", "type": "string"},
                {"name": "max_sentences", "type": "integer"},
            ],
            "outputs": [{"name": "summary", "type": "string"}],
            "nodes": [
                {
                    "id": "prompt",
                    "op": "template.render",
                    "config": {"template": "Summarize in {{max_sentences}} sentences:\n{{text}}"},
                },
                {
                    "id": "gen",
                    "op": "llm.generate",
                    "inputs": {"prompt": "prompt.rendered"},
                },
            ],
            "edges": [
                {"from": "input.text", "to": "prompt.text"},
                {"from": "input.max_sentences", "to": "prompt.max_sentences"},
            ],
            "graph_outputs": {"summary": "gen.text"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(data), goal="summarize")
        assert result.status == "success"
        assert result.graph is not None
        assert len(result.graph.graph.nodes) == 2

    def test_validates_against_skill_package(self) -> None:
        result = parse_planner_output(_valid_plan_json(), goal="test")
        assert result.graph is not None
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)  # should not raise

    def test_code_fenced_json(self) -> None:
        raw = f"```json\n{_valid_plan_json()}\n```"
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"

    def test_bare_code_fence(self) -> None:
        raw = f"```\n{_valid_plan_json()}\n```"
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"


# ── partial output ───────────────────────────────────────────────────


class TestPartialOutput:
    def test_with_holes(self) -> None:
        raw = _valid_plan_json(
            holes=[
                {
                    "node_id": "step2",
                    "kind": "missing_skill",
                    "description": "No skill for PDF extraction.",
                }
            ]
        )
        result = parse_planner_output(raw, goal="test")
        assert result.status == "partial"
        assert result.graph is not None
        assert len(result.holes) == 1
        assert result.holes[0].kind == "missing_skill"
        assert "PDF" in result.holes[0].description

    def test_invalid_hole_kind_normalized(self) -> None:
        raw = _valid_plan_json(
            holes=[{"node_id": "x", "kind": "bogus_kind", "description": "test"}]
        )
        result = parse_planner_output(raw, goal="test")
        assert result.status == "partial"
        assert result.holes[0].kind == "missing_skill"  # normalized


# ── malformed output ─────────────────────────────────────────────────


class TestMalformedOutput:
    def test_not_json(self) -> None:
        result = parse_planner_output("This is not JSON at all.", goal="test")
        assert result.status == "failure"
        assert len(result.holes) == 1
        assert result.holes[0].kind == "validation_error"
        assert "Invalid JSON" in result.holes[0].description

    def test_json_array(self) -> None:
        result = parse_planner_output("[1, 2, 3]", goal="test")
        assert result.status == "failure"
        assert "Expected JSON object" in result.holes[0].description

    def test_missing_required_keys(self) -> None:
        raw = json.dumps({"inputs": [], "outputs": []})
        result = parse_planner_output(raw, goal="test")
        assert result.status == "failure"
        assert "Missing required keys" in result.holes[0].description
        assert "edges" in result.holes[0].description
        assert "nodes" in result.holes[0].description

    def test_invalid_node_structure(self) -> None:
        raw = json.dumps({
            "inputs": [{"name": "x", "type": "string"}],
            "outputs": [{"name": "y", "type": "string"}],
            "nodes": [{"missing_id": True}],  # no 'id' or 'op'
            "edges": [],
            "graph_outputs": {"y": "step.out"},
        })
        result = parse_planner_output(raw, goal="test")
        assert result.status == "failure"
        assert "Failed to build" in result.holes[0].description

    def test_empty_string(self) -> None:
        result = parse_planner_output("", goal="test")
        assert result.status == "failure"


# ── validation after parsing ─────────────────────────────────────────


class TestPostParseValidation:
    def test_invalid_op_becomes_partial(self) -> None:
        """Graph parses OK but uses an invalid op -> validation demotes to partial."""
        data = {
            "inputs": [{"name": "x", "type": "string"}],
            "outputs": [{"name": "y", "type": "string"}],
            "nodes": [{"id": "bad", "op": "magic.spell", "config": {}}],
            "edges": [{"from": "input.x", "to": "bad.x"}],
            "graph_outputs": {"y": "bad.out"},
        }
        raw = json.dumps(data)
        result = parse_planner_output(raw, goal="test")
        # Parser succeeds, but compose_plan validates
        assert result.status == "success"  # parser itself doesn't validate

        # But when run through compose_plan pipeline, validation catches it
        from graphsmith.planner.composer import _validate_glue_graph
        validated = _validate_glue_graph(result)
        assert validated.status == "partial"
        assert any(h.kind == "validation_error" for h in validated.holes)


# ── LLMPlannerBackend integration ────────────────────────────────────


class TestLLMBackendParsing:
    def test_canned_valid_response(self) -> None:
        provider = _CannedLLMProvider(_valid_plan_json())
        backend = LLMPlannerBackend(provider=provider)

        from graphsmith.planner.models import PlanRequest
        from graphsmith.registry.index import IndexEntry

        request = PlanRequest(
            goal="test",
            candidates=[
                IndexEntry(
                    id="test.v1", name="Test", version="1.0.0",
                    description="test", input_names=["text"],
                    output_names=["result"],
                )
            ],
        )
        result = backend.compose(request)
        assert result.status == "success"
        assert result.graph is not None

    def test_canned_invalid_response(self) -> None:
        provider = _CannedLLMProvider("not valid json")
        backend = LLMPlannerBackend(provider=provider)

        from graphsmith.planner.models import PlanRequest
        request = PlanRequest(goal="test", candidates=[])
        result = backend.compose(request)
        assert result.status == "failure"

    def test_provider_exception(self) -> None:
        class FailProvider:
            def generate(self, prompt: str, **kw: Any) -> str:
                raise RuntimeError("API down")
            def extract(self, prompt: str, schema: dict, **kw: Any) -> dict:
                return {}

        backend = LLMPlannerBackend(provider=FailProvider())
        from graphsmith.planner.models import PlanRequest
        request = PlanRequest(goal="test", candidates=[])
        result = backend.compose(request)
        assert result.status == "failure"
        assert "API down" in result.reasoning


# ── CLI with LLM backend ────────────────────────────────────────────


class TestCLIPlannerBackend:
    def test_plan_with_auto_backend_default(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        reg_root = tmp_path / "reg"
        runner.invoke(app, [
            "publish", str(EXAMPLE_DIR / "text.summarize.v1"),
            "--registry", str(reg_root),
        ])
        result = runner.invoke(app, [
            "plan", "summarize text",
            "--registry", str(reg_root),
            "--output-format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"

    def test_resolve_auto_backend_prefers_mock_without_provider(self) -> None:
        from graphsmith.cli.main import _resolve_planner_backend_name

        backend = _resolve_planner_backend_name(
            "auto",
            mock_llm=False,
            provider="echo",
            model=None,
            base_url=None,
        )
        assert backend == "mock"

    def test_resolve_auto_backend_prefers_ir_when_llm_is_requested(self) -> None:
        from graphsmith.cli.main import _resolve_planner_backend_name

        assert _resolve_planner_backend_name(
            "auto",
            mock_llm=True,
            provider="echo",
            model=None,
            base_url=None,
        ) == "ir"
        assert _resolve_planner_backend_name(
            "auto",
            mock_llm=False,
            provider="anthropic",
            model=None,
            base_url=None,
        ) == "ir"

    def test_plan_with_llm_backend_missing_api_key_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        # Ensure no API key in env
        monkeypatch.delenv("GRAPHSMITH_ANTHROPIC_API_KEY", raising=False)
        result = runner.invoke(app, [
            "plan", "test",
            "--backend", "llm",
            "--provider", "anthropic",
            "--registry", str(tmp_path / "reg"),
        ])
        assert result.exit_code == 1
        assert "API key" in result.output or "FAIL" in result.output

    def test_plan_show_retrieval_in_text_output(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        reg_root = tmp_path / "reg"
        runner.invoke(app, [
            "publish", str(EXAMPLE_DIR / "text.summarize.v1"),
            "--registry", str(reg_root),
        ])
        result = runner.invoke(app, [
            "plan", "summarize text",
            "--registry", str(reg_root),
            "--show-retrieval",
        ])
        assert result.exit_code == 0
        assert "Retrieval [ranked]" in result.output
        assert "text.summarize.v1" in result.output
