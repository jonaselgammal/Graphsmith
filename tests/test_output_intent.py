"""Tests for Sprint 19: deliverable vs intermediate output intent."""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import PROMPT_VERSION, build_planning_context
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.validator import validate_skill_package


# ── prompt content ───────────────────────────────────────────────────


class TestPromptOutputIntent:
    def test_version_v5(self) -> None:
        assert PROMPT_VERSION == "v7"

    def test_teaches_and_vs_then(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        lower = ctx.lower()
        assert "and extract keywords" in lower
        assert "and then summarize" in lower

    def test_has_contrasting_examples(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        # Example 2a: hidden intermediate
        assert "intermediate hidden" in ctx.lower() or "just a step" in ctx.lower()
        # Example 2b: both exposed
        assert "both results exposed" in ctx.lower() or "expose both" in ctx.lower()

    def test_example2a_hides_normalized(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        # Example 2a should map only summary
        assert '"summary": "summarize.summary"' in ctx

    def test_example2b_exposes_both(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        # Example 2b should map both normalized and keywords
        assert '"normalized": "normalize.normalized"' in ctx
        assert '"keywords": "extract.keywords"' in ctx

    def test_key_test_question(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "user wants back" in ctx.lower()


# ── canned plan patterns ─────────────────────────────────────────────


class TestNormalizeAndExtract:
    """Goal: 'Normalize this text and extract keywords' → expose both."""

    def test_both_outputs_exposed(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [
                {"name": "normalized", "type": "string"},
                {"name": "keywords", "type": "string"},
            ],
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
            "graph_outputs": {
                "normalized": "norm.normalized",
                "keywords": "kw.keywords",
            },
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
        assert "normalized" in result.graph.graph.outputs
        assert "keywords" in result.graph.graph.outputs
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)


class TestNormalizeThenSummarize:
    """Goal: 'Normalize and then summarize' → hide normalized."""

    def test_only_summary_exposed(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "summary", "type": "string"}],
            "nodes": [
                {"id": "norm", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
                {"id": "sum", "op": "skill.invoke",
                 "config": {"skill_id": "text.summarize.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "norm.text"},
                {"from": "norm.normalized", "to": "sum.text"},
            ],
            "graph_outputs": {"summary": "sum.summary"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
        assert set(result.graph.graph.outputs.keys()) == {"summary"}


class TestNormalizeSummarizeAndExtract:
    """Goal: 'normalize, summarize, and extract keywords' → expose summary + keywords."""

    def test_summary_and_keywords_exposed(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [
                {"name": "summary", "type": "string"},
                {"name": "keywords", "type": "string"},
            ],
            "nodes": [
                {"id": "norm", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
                {"id": "sum", "op": "skill.invoke",
                 "config": {"skill_id": "text.summarize.v1", "version": "1.0.0"}},
                {"id": "kw", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "norm.text"},
                {"from": "norm.normalized", "to": "sum.text"},
                {"from": "norm.normalized", "to": "kw.text"},
            ],
            "graph_outputs": {
                "summary": "sum.summary",
                "keywords": "kw.keywords",
            },
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
        assert "summary" in result.graph.graph.outputs
        assert "keywords" in result.graph.graph.outputs
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)


# ── no regression: formatting chain still works ──────────────────────


class TestFormattingChainNotRegressed:
    def test_extract_then_format(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "joined", "type": "string"}],
            "nodes": [
                {"id": "kw", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
                {"id": "fmt", "op": "skill.invoke",
                 "config": {"skill_id": "text.join_lines.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "kw.text"},
                {"from": "kw.keywords", "to": "fmt.lines"},
            ],
            "graph_outputs": {"joined": "fmt.joined"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
        assert set(result.graph.graph.outputs.keys()) == {"joined"}
