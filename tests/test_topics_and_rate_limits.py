"""Tests for Sprint 28: topics semantics and rate-limit safety."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphsmith.evaluation.planner_eval import (
    EvalGoal, EvalResult, _classify_failure, evaluate_goal, run_evaluation,
)
from graphsmith.planner import MockPlannerBackend
from graphsmith.planner.models import PlanRequest
from graphsmith.planner.prompt import build_planning_context
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.registry import LocalRegistry
from graphsmith.validator import validate_skill_package

from conftest import EXAMPLE_DIR

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture()
def full_reg(tmp_path: Path) -> LocalRegistry:
    r = LocalRegistry(root=tmp_path / "reg")
    for d in sorted((EXAMPLE_DIR).iterdir()):
        if d.is_dir():
            r.publish(d)
    return r


# ── topic/keyword semantic mapping ───────────────────────────────────


class TestTopicKeywordMapping:
    def test_prompt_teaches_topics_to_keywords(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        lower = ctx.lower()
        assert "topics" in lower
        assert "keywords" in lower

    def test_prompt_enforces_skill_port_names(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "NEVER use the goal's phrasing" in ctx or "skill's port name" in ctx.lower()

    def test_correct_topics_plan_uses_keywords_output(self) -> None:
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
        assert "keywords" in result.graph.graph.outputs
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)

    def test_holdout_goal_accepts_topics_or_keywords(self) -> None:
        from graphsmith.evaluation.planner_eval import load_goals
        holdout = Path(__file__).parent.parent / "evaluation" / "holdout_goals"
        goals = load_goals(holdout)
        topic_goal = [g for g in goals if "topics" in g.goal.lower()]
        assert len(topic_goal) >= 1
        g = topic_goal[0]
        assert g.acceptable_output_names or g.expected_output_names


# ── failure classification ───────────────────────────────────────────


class TestFailureClassification:
    def test_provider_429(self) -> None:
        r = EvalResult(
            goal="test", status="fail",
            error="Anthropic API error (429): rate limit exceeded",
            expected_skills_in_shortlist=True,
        )
        assert _classify_failure(r) == "provider"

    def test_provider_in_holes(self) -> None:
        r = EvalResult(
            goal="test", status="fail",
            holes=["Provider error: 429 rate limit"],
            expected_skills_in_shortlist=True,
        )
        assert _classify_failure(r) == "provider"

    def test_retrieval_failure(self) -> None:
        r = EvalResult(
            goal="test", status="fail",
            expected_skills_in_shortlist=False,
        )
        assert _classify_failure(r) == "retrieval"

    def test_planner_failure(self) -> None:
        r = EvalResult(
            goal="test", status="partial",
            error="wrong outputs",
            expected_skills_in_shortlist=True,
        )
        assert _classify_failure(r) == "planner"


# ── throttled evaluation ─────────────────────────────────────────────


class TestThrottledEvaluation:
    def test_delay_parameter_accepted(self, full_reg: LocalRegistry) -> None:
        goals = [EvalGoal(goal="normalize text", expected_skills=["text.normalize.v1"])]
        report = run_evaluation(
            goals, full_reg, MockPlannerBackend(),
            delay_seconds=0.0,  # no actual delay in tests
        )
        assert report.goals_total == 1


# ── scripts exist ────────────────────────────────────────────────────


class TestSafeScripts:
    @pytest.mark.parametrize("script", [
        "eval_compare_safe.sh",
        "eval_holdout_modes_safe.sh",
    ])
    def test_exists_and_executable(self, script: str) -> None:
        import os
        path = SCRIPTS_DIR / script
        assert path.exists()
        assert os.access(path, os.X_OK)

    def test_compare_safe_has_delay(self) -> None:
        content = (SCRIPTS_DIR / "eval_compare_safe.sh").read_text()
        assert "DELAY" in content
        assert "--delay" in content
