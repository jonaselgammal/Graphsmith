"""Tests for candidate-level dataset collection and labeling."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from graphsmith.evaluation.candidate_dataset import (
    CandidateGroup,
    CandidateSample,
    analyze_groups,
    build_group,
    build_sample,
    export_groups,
    export_samples,
    label_candidate,
    load_groups,
    load_samples,
    print_analysis,
)
from graphsmith.evaluation.planner_eval import EvalGoal
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.planner.ir import IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.ir_backend import CandidateResult
from graphsmith.planner.ir_scorer import ScoreBreakdown
from graphsmith.planner.models import GlueGraph


# ── Helpers ────────────────────────────────────────────────────────


def _make_glue(skill_id: str, output_name: str, output_port: str) -> GlueGraph:
    return GlueGraph(
        goal="test",
        inputs=[IOField(name="text", type="string")],
        outputs=[IOField(name=output_name, type="string")],
        effects=["llm_inference"],
        graph=GraphBody(
            version=1,
            nodes=[GraphNode(id="n", op="skill.invoke", config={"skill_id": skill_id, "version": "1.0.0"})],
            edges=[GraphEdge(from_="input.text", to="n.text")],
            outputs={output_name: f"n.{output_port}"},
        ),
    )


def _make_candidate(
    index: int,
    skill_id: str,
    output_name: str,
    output_port: str,
    score: float = 100.0,
) -> CandidateResult:
    ir = PlanningIR(
        goal="test",
        inputs=[IRInput(name="text")],
        steps=[IRStep(name="n", skill_id=skill_id,
                      sources={"text": IRSource(step="input", port="text")})],
        final_outputs={output_name: IROutputRef(step="n", port=output_port)},
    )
    glue = _make_glue(skill_id, output_name, output_port)
    return CandidateResult(
        index=index, status="compiled", ir=ir, glue=glue,
        score=ScoreBreakdown(total=score),
    )


def _make_eval_goal(
    goal: str,
    expected_skills: list[str],
    expected_output_names: list[str] | None = None,
    acceptable_output_names: list[list[str]] | None = None,
) -> EvalGoal:
    return EvalGoal(
        goal=goal,
        expected_skills=expected_skills,
        expected_output_names=expected_output_names or [],
        acceptable_output_names=acceptable_output_names or [],
    )


# ── Label assignment ───────────────────────────────────────────────


class TestLabelCandidate:
    def test_passing_candidate(self) -> None:
        cand = _make_candidate(0, "text.extract_keywords.v1", "keywords", "keywords")
        goal = _make_eval_goal("test", ["text.extract_keywords.v1"], ["keywords"])
        validates, passes, fc = label_candidate(cand, goal)
        assert validates is True
        assert passes is True
        assert fc == ""

    def test_wrong_skill(self) -> None:
        cand = _make_candidate(0, "json.reshape.v1", "selected", "selected")
        goal = _make_eval_goal("test", ["text.extract_keywords.v1"], ["keywords"])
        validates, passes, fc = label_candidate(cand, goal)
        assert validates is True
        assert passes is False
        assert "wrong_skill" in fc

    def test_wrong_output(self) -> None:
        cand = _make_candidate(0, "text.extract_keywords.v1", "joined", "keywords")
        goal = _make_eval_goal("test", ["text.extract_keywords.v1"], ["keywords"])
        validates, passes, fc = label_candidate(cand, goal)
        assert validates is True
        assert passes is False
        assert "wrong_output" in fc

    def test_invalid_candidate(self) -> None:
        cand = CandidateResult(index=0, status="parse_error", error="bad json")
        goal = _make_eval_goal("test", ["text.extract_keywords.v1"])
        validates, passes, fc = label_candidate(cand, goal)
        assert validates is False
        assert passes is False
        assert fc == "invalid_candidate"

    def test_acceptable_output_names(self) -> None:
        cand = _make_candidate(0, "text.extract_keywords.v1", "formatted", "keywords")
        goal = _make_eval_goal("test", ["text.extract_keywords.v1"],
                               acceptable_output_names=[["formatted", "result"]])
        _, passes, fc = label_candidate(cand, goal)
        assert passes is True


# ── Sample building ────────────────────────────────────────────────


class TestBuildSample:
    def test_basic_sample(self) -> None:
        cand = _make_candidate(0, "text.extract_keywords.v1", "keywords", "keywords", score=115.0)
        goal = _make_eval_goal("Extract keywords", ["text.extract_keywords.v1"], ["keywords"])
        sample = build_sample(cand, goal, run_index=1)
        assert sample.goal == "Extract keywords"
        assert sample.run_index == 1
        assert sample.has_extract_keywords is True
        assert sample.would_pass_eval is True
        assert sample.det_score == 115.0

    def test_goal_features(self) -> None:
        cand = _make_candidate(0, "text.extract_keywords.v1", "keywords", "keywords")
        goal = _make_eval_goal("Extract keywords and format as a list",
                               ["text.extract_keywords.v1"])
        sample = build_sample(cand, goal)
        assert sample.goal_mentions_keywords is True
        assert sample.goal_mentions_format is True
        assert sample.goal_mentions_json is False


# ── Group building and ranking ─────────────────────────────────────


class TestBuildGroup:
    def test_group_with_passing_winner(self) -> None:
        good = _make_candidate(0, "text.extract_keywords.v1", "keywords", "keywords", 115)
        bad = _make_candidate(1, "text.extract_keywords.v1", "joined", "keywords", 80)
        goal = _make_eval_goal("test", ["text.extract_keywords.v1"], ["keywords"])
        samples = [
            build_sample(good, goal, was_selected=True),
            build_sample(bad, goal, was_selected=False),
        ]
        group = build_group(samples, selected_index=0)
        assert group.selected_passes is True
        assert group.oracle_passes is True
        assert group.has_passing_candidate is True
        assert samples[0].rank == 1
        assert samples[0].is_best is True

    def test_group_with_better_unselected(self) -> None:
        bad = _make_candidate(0, "json.reshape.v1", "selected", "selected", 100)
        good = _make_candidate(1, "text.extract_keywords.v1", "keywords", "keywords", 90)
        goal = _make_eval_goal("test", ["text.extract_keywords.v1"], ["keywords"])
        samples = [
            build_sample(bad, goal, was_selected=True),
            build_sample(good, goal, was_selected=False),
        ]
        group = build_group(samples, selected_index=0)
        assert group.selected_passes is False
        assert group.oracle_passes is True
        assert group.has_passing_candidate is True
        assert samples[1].beats_selected is True
        assert samples[1].is_best is True

    def test_group_all_fail(self) -> None:
        c1 = _make_candidate(0, "json.reshape.v1", "selected", "selected", 100)
        c2 = _make_candidate(1, "json.reshape.v1", "selected", "selected", 90)
        goal = _make_eval_goal("test", ["text.extract_keywords.v1"], ["keywords"])
        samples = [build_sample(c1, goal), build_sample(c2, goal)]
        group = build_group(samples, selected_index=0)
        assert group.selected_passes is False
        assert group.oracle_passes is False
        assert group.has_passing_candidate is False


# ── Analysis ───────────────────────────────────────────────────────


class TestAnalysis:
    def test_headroom_calculation(self) -> None:
        g1 = CandidateGroup(
            goal="g1", selected_passes=True, oracle_passes=True,
            has_passing_candidate=True, selected_index=0, best_index=0,
            candidates=[CandidateSample(goal="g1", would_pass_eval=True)],
        )
        g2 = CandidateGroup(
            goal="g2", selected_passes=False, oracle_passes=True,
            has_passing_candidate=True, selected_index=0, best_index=1,
            candidates=[
                CandidateSample(goal="g2", would_pass_eval=False, failure_class="wrong_output_name"),
                CandidateSample(goal="g2", would_pass_eval=True),
            ],
        )
        g3 = CandidateGroup(
            goal="g3", selected_passes=False, oracle_passes=False,
            has_passing_candidate=False, selected_index=0, best_index=0,
            candidates=[
                CandidateSample(goal="g3", would_pass_eval=False, failure_class="wrong_skill_selection"),
            ],
        )
        analysis = analyze_groups([g1, g2, g3])
        assert analysis["total_groups"] == 3
        assert analysis["selected_passes"] == 1
        assert analysis["oracle_passes"] == 2
        assert analysis["reranking_headroom"] == 1
        assert analysis["better_available"] == 1

    def test_print_analysis(self) -> None:
        analysis = {
            "total_groups": 10,
            "has_passing_candidate": 8,
            "selected_passes": 7,
            "oracle_passes": 8,
            "selected_pass_rate": 0.7,
            "oracle_pass_rate": 0.8,
            "reranking_headroom": 1,
            "better_available": 1,
            "total_candidates": 30,
            "total_passing_candidates": 20,
            "candidate_pass_rate": 0.667,
            "failure_classes": {"wrong_output_name": 2},
        }
        text = print_analysis(analysis)
        assert "headroom" in text.lower()
        assert "oracle" in text.lower()


# ── Export/import ──────────────────────────────────────────────────


class TestExportImport:
    def test_samples_roundtrip(self) -> None:
        samples = [
            CandidateSample(goal="g1", candidate_index=0, would_pass_eval=True, det_score=115),
            CandidateSample(goal="g1", candidate_index=1, would_pass_eval=False, det_score=80),
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        export_samples(samples, path)
        loaded = load_samples(path)
        assert len(loaded) == 2
        assert loaded[0].det_score == 115
        assert loaded[1].would_pass_eval is False
        Path(path).unlink()

    def test_groups_roundtrip(self) -> None:
        groups = [
            CandidateGroup(
                goal="g1", selected_passes=True, oracle_passes=True,
                candidates=[CandidateSample(goal="g1", would_pass_eval=True)],
            ),
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        export_groups(groups, path)
        loaded = load_groups(path)
        assert len(loaded) == 1
        assert loaded[0].selected_passes is True
        assert len(loaded[0].candidates) == 1
        Path(path).unlink()
