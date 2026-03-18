"""Tests for Sprint 21: paraphrase robustness for output intent."""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import PROMPT_VERSION, build_planning_context
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.validator import validate_skill_package


# ── prompt content ───────────────────────────────────────────────────


class TestPromptParaphraseGuidance:
    def test_version_v6(self) -> None:
        assert PROMPT_VERSION == "v7"

    def test_has_paraphrase_rule(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "tidy up" in ctx.lower()
        assert "clean" in ctx.lower()
        assert "find topics" in ctx.lower()

    def test_has_comma_list_rule(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "commas" in ctx.lower() or "X, Y, and Z" in ctx

    def test_has_paraphrased_example(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "clean the text" in ctx.lower()
        assert "write a summary" in ctx.lower()
        assert "list the keywords" in ctx.lower()

    def test_paraphrased_example_exposes_both(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert '"summary": "summarize.summary"' in ctx
        assert '"keywords": "extract.keywords"' in ctx


# ── canned plan: tidy up and find topics ─────────────────────────────


class TestTidyUpAndFindTopics:
    """Holdout h05: 'Tidy up this text and find the key topics'."""

    def test_correct_plan_exposes_both(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [
                {"name": "normalized", "type": "string"},
                {"name": "keywords", "type": "string"},
            ],
            "nodes": [
                {"id": "normalize", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
                {"id": "extract", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "normalize.text"},
                {"from": "normalize.normalized", "to": "extract.text"},
            ],
            "graph_outputs": {
                "normalized": "normalize.normalized",
                "keywords": "extract.keywords",
            },
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
        assert "normalized" in result.graph.graph.outputs
        assert "keywords" in result.graph.graph.outputs
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)


# ── canned plan: clean, summarize, and list keywords ─────────────────


class TestCleanSummarizeAndListKeywords:
    """Holdout h08: 'Clean the text, write a summary, and list the keywords'."""

    def test_correct_plan_exposes_summary_and_keywords(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [
                {"name": "summary", "type": "string"},
                {"name": "keywords", "type": "string"},
            ],
            "nodes": [
                {"id": "normalize", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
                {"id": "summarize", "op": "skill.invoke",
                 "config": {"skill_id": "text.summarize.v1", "version": "1.0.0"}},
                {"id": "extract", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "normalize.text"},
                {"from": "normalize.normalized", "to": "summarize.text"},
                {"from": "normalize.normalized", "to": "extract.text"},
            ],
            "graph_outputs": {
                "summary": "summarize.summary",
                "keywords": "extract.keywords",
            },
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
        assert "summary" in result.graph.graph.outputs
        assert "keywords" in result.graph.graph.outputs
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)


# ── no regression: existing patterns ─────────────────────────────────


class TestNoRegression:
    def test_hidden_intermediate_still_works(self) -> None:
        """'Normalize then summarize' → only summary."""
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "summary", "type": "string"}],
            "nodes": [
                {"id": "n", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
                {"id": "s", "op": "skill.invoke",
                 "config": {"skill_id": "text.summarize.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "n.text"},
                {"from": "n.normalized", "to": "s.text"},
            ],
            "graph_outputs": {"summary": "s.summary"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
        assert set(result.graph.graph.outputs.keys()) == {"summary"}

    def test_formatting_chain_still_works(self) -> None:
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
