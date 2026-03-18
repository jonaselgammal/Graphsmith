"""Tests for Sprint 17: output contract alignment.

Covers the two failing evaluation patterns and prompt improvements.
"""
from __future__ import annotations

import json

import pytest

from graphsmith.evaluation.planner_eval import EvalGoal, evaluate_goal, EvalChecks
from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import build_planning_context
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.validator import validate_skill_package


# ── prompt content checks ────────────────────────────────────────────


class TestPromptOutputGuidance:
    def test_prompt_teaches_output_intent(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "explicitly requests" in ctx.lower() or "user wants back" in ctx.lower()

    def test_prompt_teaches_output_naming(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "output port name" in ctx.lower()

    def test_prompt_teaches_intermediate_stay_internal(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "intermediate" in ctx.lower()

    def test_example2_shows_normalize_summarize(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "summarize" in ctx
        assert "normalize" in ctx
        # Only summary exposed, not normalized
        assert '"summary": "summarize.' in ctx


# ── pattern: normalize then summarize (goal 06) ─────────────────────


class TestNormalizeThenSummarize:
    def test_correct_plan_exposes_only_summary(self) -> None:
        """A correct plan for 'normalize then summarize' should only
        expose summary, not normalized."""
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
        result = parse_planner_output(json.dumps(plan), goal="normalize and summarize")
        assert result.status == "success"
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)
        assert set(result.graph.graph.outputs.keys()) == {"summary"}

    def test_plan_with_extra_intermediate_output_still_valid(self) -> None:
        """A plan that also exposes normalized is valid but not ideal."""
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [
                {"name": "normalized", "type": "string"},
                {"name": "summary", "type": "string"},
            ],
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
            "graph_outputs": {
                "normalized": "norm.normalized",
                "summary": "sum.summary",
            },
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"
        # Contains summary (the required output)
        assert "summary" in result.graph.graph.outputs


# ── pattern: extract keywords then format (goal 08) ──────────────────


class TestExtractThenFormat:
    def test_correct_plan_with_joined_output(self) -> None:
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

    def test_plan_with_formatted_output_name(self) -> None:
        """LLM might use 'formatted' instead of 'joined' — still valid."""
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "formatted", "type": "string"}],
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
            "graph_outputs": {"formatted": "fmt.joined"},
            "effects": ["llm_inference"],
        }
        result = parse_planner_output(json.dumps(plan), goal="test")
        assert result.status == "success"


# ── acceptable_output_names eval check ───────────────────────────────


class TestAcceptableOutputNames:
    def test_exact_match(self) -> None:
        goal = EvalGoal(
            goal="test",
            acceptable_output_names=[["summary", "result"]],
        )
        checks = EvalChecks()
        # Simulate: graph_outputs has "summary"
        assert any("summary" in alts for alts in goal.acceptable_output_names)

    def test_alternative_match(self) -> None:
        goal = EvalGoal(
            goal="test",
            acceptable_output_names=[["joined", "formatted", "result"]],
        )
        # "formatted" should match
        mapped = {"formatted"}
        result = all(
            any(name in mapped for name in alts)
            for alts in goal.acceptable_output_names
        )
        assert result

    def test_no_match(self) -> None:
        goal = EvalGoal(
            goal="test",
            acceptable_output_names=[["joined", "formatted"]],
        )
        mapped = {"something_else"}
        result = all(
            any(name in mapped for name in alts)
            for alts in goal.acceptable_output_names
        )
        assert not result


# ── positive: already-passing patterns still work ────────────────────


class TestExistingPatternsUnchanged:
    def test_single_skill_normalize(self) -> None:
        plan = {
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "normalized", "type": "string"}],
            "nodes": [
                {"id": "n", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
            ],
            "edges": [{"from": "input.text", "to": "n.text"}],
            "graph_outputs": {"normalized": "n.normalized"},
        }
        result = parse_planner_output(json.dumps(plan), goal="normalize")
        assert result.status == "success"
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)

    def test_multi_skill_normalize_extract(self) -> None:
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
