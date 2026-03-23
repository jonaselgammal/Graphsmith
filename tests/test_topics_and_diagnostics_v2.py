"""Tests for Sprint 29: topics/keywords semantics fix and diagnostics hardening."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphsmith.evaluation.planner_eval import (
    EvalGoal, _classify_failure, EvalResult, load_goals,
)
from graphsmith.planner.models import PlanRequest
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import build_planning_context
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.validator import validate_skill_package

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
HOLDOUT_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "holdout_goals"


# ── prompt topics example ────────────────────────────────────────────


class TestPromptTopicsExample:
    def test_prompt_has_topics_example(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "find the key topics" in ctx.lower() or "tidy up" in ctx.lower()

    def test_prompt_shows_topics_to_keywords_mapping(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        # The example should show goal says "topics" but output is "keywords"
        assert "topics" in ctx.lower()
        assert '"keywords"' in ctx

    def test_prompt_says_never_use_goal_phrasing(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "NEVER invent" in ctx or "NEVER split" in ctx


# ── correct topics plan ──────────────────────────────────────────────


class TestCorrectTopicsPlan:
    def test_topics_output_named_keywords(self) -> None:
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
        result = parse_planner_output(json.dumps(plan), goal="find topics")
        assert result.status == "success"
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)

    def test_tidy_and_topics_plan(self) -> None:
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
        result = parse_planner_output(json.dumps(plan), goal="tidy up and find topics")
        assert result.status == "success"
        assert "normalized" in result.graph.graph.outputs
        assert "keywords" in result.graph.graph.outputs


# ── eval goals accept topics ─────────────────────────────────────────


class TestEvalGoalsAcceptTopics:
    def test_h02_accepts_topics_or_keywords(self) -> None:
        goals = load_goals(HOLDOUT_DIR)
        h02 = [g for g in goals if "key topics" in g.goal and "tidy" not in g.goal.lower()][0]
        assert h02.acceptable_output_names
        alts = h02.acceptable_output_names[0]
        assert "keywords" in alts
        assert "topics" in alts

    def test_h05_accepts_topics_or_keywords(self) -> None:
        goals = load_goals(HOLDOUT_DIR)
        h05 = [g for g in goals if "tidy" in g.goal.lower()][0]
        assert h05.acceptable_output_names
        # Should have two slots: one for normalized, one for keywords/topics
        assert len(h05.acceptable_output_names) == 2


# ── diagnostics classification ───────────────────────────────────────


class TestDiagnosticsClassification:
    def test_provider_429_classified(self) -> None:
        r = EvalResult(goal="x", status="fail", error="429 rate limit exceeded")
        assert _classify_failure(r) == "provider"

    def test_retrieval_missing_classified(self) -> None:
        r = EvalResult(goal="x", status="fail", expected_skills_in_shortlist=False)
        assert _classify_failure(r) == "retrieval"

    def test_planner_default(self) -> None:
        r = EvalResult(goal="x", status="partial", expected_skills_in_shortlist=True)
        assert _classify_failure(r) == "planner"


# ── inspect_diagnostics handles missing/empty failure_type ───────────


class TestInspectDiagnostics:
    def test_infer_from_content(self) -> None:
        from graphsmith.evaluation.diagnostics import infer_failure_type
        assert infer_failure_type({"error": "429 rate limit"}) == "provider"
        assert infer_failure_type({"expected_in_shortlist": False}) == "retrieval"
        assert infer_failure_type({"expected_in_shortlist": True, "error": "wrong"}) == "planner"


# ── scripts exist ────────────────────────────────────────────────────


class TestScripts:
    @pytest.mark.parametrize("script", [
        "eval_default_safe.sh",
        "eval_compare_safe.sh",
        "eval_holdout_modes_safe.sh",
        "eval_canonical.sh",
        "release_smoke.sh",
    ])
    def test_exists_and_executable(self, script: str) -> None:
        import os
        path = SCRIPTS_DIR / script
        assert path.exists()
        assert os.access(path, os.X_OK)

    def test_compare_safe_has_15s_pause(self) -> None:
        content = (SCRIPTS_DIR / "eval_compare_safe.sh").read_text()
        assert "sleep 15" in content

    def test_default_delay_is_3(self) -> None:
        for script in ["eval_compare_safe.sh", "eval_holdout_modes_safe.sh"]:
            content = (SCRIPTS_DIR / script).read_text()
            assert "GS_EVAL_DELAY:-3" in content

    def test_canonical_eval_uses_ir_benchmark_defaults(self) -> None:
        content = (SCRIPTS_DIR / "eval_canonical.sh").read_text()
        assert "evaluation/goals" in content
        assert "--backend ir" in content
        assert "--ir-candidates 3" in content
        assert "--decompose" in content
