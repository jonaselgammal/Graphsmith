"""Tests for Sprint 08B: prompt refinement, parser robustness, canned multi-step plans."""
from __future__ import annotations

import json
from typing import Any

import pytest

from graphsmith.constants import PRIMITIVE_OPS
from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import PROMPT_VERSION, build_planning_context, get_system_message
from graphsmith.registry.index import IndexEntry


# ── prompt content ───────────────────────────────────────────────────


class TestPromptContent:
    def _request(self, **kw: Any) -> PlanRequest:
        return PlanRequest(goal="summarize text", candidates=[], **kw)

    def test_contains_version_tag(self) -> None:
        ctx = build_planning_context(self._request())
        assert f"[graphsmith-planner-prompt {PROMPT_VERSION}]" in ctx

    def test_version_is_v4(self) -> None:
        assert PROMPT_VERSION == "v5"

    def test_contains_json_schema_keys(self) -> None:
        ctx = build_planning_context(self._request())
        for key in ("inputs", "outputs", "nodes", "edges", "graph_outputs"):
            assert f'"{key}"' in ctx

    def test_contains_valid_example(self) -> None:
        ctx = build_planning_context(self._request())
        assert "skill.invoke" in ctx
        assert "text.summarize.v1" in ctx

    def test_contains_partial_example(self) -> None:
        ctx = build_planning_context(self._request())
        assert '"holes"' in ctx
        assert "missing_skill" in ctx

    def test_contains_primitive_ops(self) -> None:
        ctx = build_planning_context(self._request())
        for op in ("template.render", "llm.generate", "skill.invoke"):
            assert op in ctx

    def test_contains_json_only_instruction(self) -> None:
        ctx = build_planning_context(self._request())
        assert "ONLY a JSON object" in ctx

    def test_contains_goal(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="custom goal", candidates=[]))
        assert "custom goal" in ctx

    def test_contains_candidates(self) -> None:
        entry = IndexEntry(
            id="my.skill.v1", name="My Skill", version="1.0.0",
            description="does stuff", input_names=["x"], output_names=["y"],
        )
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[entry]))
        assert "my.skill.v1@1.0.0" in ctx

    def test_system_message(self) -> None:
        msg = get_system_message()
        assert "JSON" in msg
        assert "Graphsmith" in msg


# ── parser: extraction robustness ────────────────────────────────────


def _valid_json() -> str:
    return json.dumps({
        "inputs": [{"name": "text", "type": "string"}],
        "outputs": [{"name": "result", "type": "string"}],
        "nodes": [{"id": "s", "op": "template.render", "config": {"template": "{{text}}"}}],
        "edges": [{"from": "input.text", "to": "s.text"}],
        "graph_outputs": {"result": "s.rendered"},
    })


class TestParserExtraction:
    def test_raw_json(self) -> None:
        result = parse_planner_output(_valid_json(), goal="test")
        assert result.status == "success"

    def test_fenced_json(self) -> None:
        raw = f"```json\n{_valid_json()}\n```"
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"

    def test_bare_fence(self) -> None:
        raw = f"```\n{_valid_json()}\n```"
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"

    def test_leading_prose(self) -> None:
        raw = f"Here is the plan:\n\n{_valid_json()}"
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"

    def test_trailing_prose(self) -> None:
        raw = f"{_valid_json()}\n\nThis should work well."
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"

    def test_surrounded_by_prose(self) -> None:
        raw = f"I'll compose a graph:\n{_valid_json()}\nLet me know if you need changes."
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"

    def test_fenced_with_surrounding_prose(self) -> None:
        raw = f"Here's the plan:\n\n```json\n{_valid_json()}\n```\n\nDone!"
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"

    def test_still_rejects_garbage(self) -> None:
        result = parse_planner_output("no json here at all", goal="test")
        assert result.status == "failure"

    def test_still_rejects_truncated_json(self) -> None:
        truncated = _valid_json()[:50]
        result = parse_planner_output(truncated, goal="test")
        assert result.status == "failure"

    def test_still_rejects_array(self) -> None:
        result = parse_planner_output("[1, 2, 3]", goal="test")
        assert result.status == "failure"


# ── canned multi-step plans ──────────────────────────────────────────


class TestCannedMultiStep:
    def test_two_node_template_then_llm(self) -> None:
        """A realistic two-step plan: template.render → llm.generate."""
        plan = {
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
            "reasoning": "Built a 2-step summarization graph.",
        }
        result = parse_planner_output(json.dumps(plan), goal="summarize")
        assert result.status == "success"
        assert result.graph is not None
        assert len(result.graph.graph.nodes) == 2
        assert result.graph.effects == ["llm_inference"]
        assert result.reasoning == "Built a 2-step summarization graph."

    def test_three_node_with_skill_invoke(self) -> None:
        """Three nodes: template → skill.invoke → select.fields."""
        plan = {
            "inputs": [{"name": "query", "type": "string"}],
            "outputs": [{"name": "title", "type": "string"}],
            "nodes": [
                {
                    "id": "fmt",
                    "op": "template.render",
                    "config": {"template": "Search: {{query}}"},
                },
                {
                    "id": "search",
                    "op": "skill.invoke",
                    "config": {"skill_id": "search.web.v1", "version": "1.0.0"},
                },
                {
                    "id": "pick",
                    "op": "select.fields",
                    "config": {"fields": ["title"]},
                },
            ],
            "edges": [
                {"from": "input.query", "to": "fmt.query"},
                {"from": "fmt.rendered", "to": "search.query"},
                {"from": "search.results", "to": "pick.data"},
            ],
            "graph_outputs": {"title": "pick.selected"},
            "effects": ["network_read"],
        }
        result = parse_planner_output(json.dumps(plan), goal="search")
        assert result.status == "success"
        assert len(result.graph.graph.nodes) == 3

    def test_partial_plan_with_holes(self) -> None:
        """LLM returns a plan with explicit holes."""
        plan = {
            "inputs": [{"name": "url", "type": "string"}],
            "outputs": [{"name": "summary", "type": "string"}],
            "nodes": [
                {
                    "id": "render",
                    "op": "template.render",
                    "config": {"template": "Summarize: {{text}}"},
                },
            ],
            "edges": [{"from": "input.url", "to": "render.text"}],
            "graph_outputs": {"summary": "render.rendered"},
            "holes": [
                {
                    "node_id": "(missing)",
                    "kind": "missing_skill",
                    "description": "No skill to fetch URL content and extract text.",
                }
            ],
            "reasoning": "Cannot fetch URL — missing a web fetcher skill.",
        }
        result = parse_planner_output(json.dumps(plan), goal="url summary")
        assert result.status == "partial"
        assert result.graph is not None
        assert len(result.holes) == 1
        assert result.holes[0].kind == "missing_skill"
        assert "URL" in result.holes[0].description

    def test_multi_step_wrapped_in_prose(self) -> None:
        """LLM wraps the JSON in explanation text."""
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "result", "type": "string"}],
            "nodes": [{"id": "s", "op": "template.render", "config": {"template": "{{text}}"}}],
            "edges": [{"from": "input.text", "to": "s.text"}],
            "graph_outputs": {"result": "s.rendered"},
        }
        raw = (
            "I've composed the following graph for your goal:\n\n"
            f"```json\n{json.dumps(plan, indent=2)}\n```\n\n"
            "This graph uses a simple template rendering approach."
        )
        result = parse_planner_output(raw, goal="test")
        assert result.status == "success"
        assert result.graph is not None


# ── provider JSON hints stay isolated ────────────────────────────────


class TestProviderIsolation:
    def test_parser_does_not_import_providers(self) -> None:
        """Parser module should not reference any provider."""
        import graphsmith.planner.parser as p
        source = open(p.__file__).read()
        assert "AnthropicProvider" not in source
        assert "OpenAICompatibleProvider" not in source
        assert "httpx" not in source

    def test_prompt_does_not_import_providers(self) -> None:
        """Prompt module should not reference any provider."""
        import graphsmith.planner.prompt as p
        source = open(p.__file__).read()
        assert "AnthropicProvider" not in source
        assert "httpx" not in source
