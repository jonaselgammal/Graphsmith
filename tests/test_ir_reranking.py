"""Tests for IR Sprint 4: candidate reranking with semantic scoring."""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.compiler import compile_ir
from graphsmith.planner.ir import IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.ir_backend import CandidateResult, IRPlannerBackend
from graphsmith.planner.ir_scorer import ScoreBreakdown, score_candidate
from graphsmith.planner.models import PlanRequest


# ── Helper ─────────────────────────────────────────────────────────

def _make_ir(
    goal: str,
    steps: list[tuple[str, str]],
    final_outputs: dict[str, tuple[str, str]],
    *,
    sources: dict[str, dict[str, tuple[str, str]]] | None = None,
    configs: dict[str, dict] | None = None,
) -> PlanningIR:
    """Shorthand IR builder for tests."""
    ir_steps = []
    default_sources = sources or {}
    default_configs = configs or {}
    for name, skill_id in steps:
        step_sources = {}
        if name in default_sources:
            for port, (src_step, src_port) in default_sources[name].items():
                step_sources[port] = IRSource(step=src_step, port=src_port)
        else:
            # Default: first step gets input.text, others get previous step
            if not ir_steps:
                step_sources = {"text": IRSource(step="input", port="text")}
            else:
                prev = ir_steps[-1].name
                step_sources = {"text": IRSource(step=prev, port="output")}
        ir_steps.append(IRStep(
            name=name, skill_id=skill_id, sources=step_sources,
            config=default_configs.get(name, {}),
        ))
    ir_outputs = {
        name: IROutputRef(step=step, port=port)
        for name, (step, port) in final_outputs.items()
    }
    return PlanningIR(
        goal=goal,
        inputs=[IRInput(name="text")],
        steps=ir_steps,
        final_outputs=ir_outputs,
        effects=["llm_inference"],
    )


# ── D1: Over-composition preference ───────────────────────────────


class TestOverCompositionPreference:
    def test_plain_extraction_prefers_minimal(self) -> None:
        """For 'extract keywords', 1-step should outrank 2-step with join_lines."""
        good = _make_ir(
            "extract keywords",
            [("extract", "text.extract_keywords.v1")],
            {"keywords": ("extract", "keywords")},
        )
        bad = _make_ir(
            "extract keywords",
            [("extract", "text.extract_keywords.v1"), ("format", "text.join_lines.v1")],
            {"joined": ("format", "joined")},
            sources={
                "extract": {"text": ("input", "text")},
                "format": {"lines": ("extract", "keywords")},
            },
        )
        score_good = score_candidate(good, "extract keywords")
        score_bad = score_candidate(bad, "extract keywords")
        assert score_good.total > score_bad.total
        # Bad should have unnecessary_formatting penalty
        penalty_reasons = [r for r, _ in score_bad.penalties]
        assert any("unnecessary_formatting" in r for r in penalty_reasons)

    def test_summarize_prefers_single_step(self) -> None:
        good = _make_ir(
            "summarize",
            [("summarize", "text.summarize.v1")],
            {"summary": ("summarize", "summary")},
        )
        bad = _make_ir(
            "summarize",
            [("summarize", "text.summarize.v1"), ("format", "text.join_lines.v1")],
            {"joined": ("format", "joined")},
            sources={
                "summarize": {"text": ("input", "text")},
                "format": {"lines": ("summarize", "summary")},
            },
        )
        assert score_candidate(good, "summarize this text").total > \
               score_candidate(bad, "summarize this text").total


# ── D2: Explicit formatting preference ────────────────────────────


class TestExplicitFormattingPreference:
    def test_list_format_prefers_formatted(self) -> None:
        """For 'format as a list', 2-step should outrank 1-step."""
        minimal = _make_ir(
            "format list",
            [("extract", "text.extract_keywords.v1")],
            {"keywords": ("extract", "keywords")},
        )
        formatted = _make_ir(
            "format list",
            [("extract", "text.extract_keywords.v1"), ("format", "text.join_lines.v1")],
            {"joined": ("format", "joined")},
            sources={
                "extract": {"text": ("input", "text")},
                "format": {"lines": ("extract", "keywords")},
            },
        )
        goal = "extract keywords and format them as a list"
        score_min = score_candidate(minimal, goal)
        score_fmt = score_candidate(formatted, goal)
        # Formatted should NOT be penalized for formatting when goal asks for it
        format_penalties = [r for r, _ in score_fmt.penalties if "unnecessary_formatting" in r]
        assert len(format_penalties) == 0
        # Minimal misses extract_keywords reward — but formatted has it too
        # Key: formatted should not lose to minimal
        assert score_fmt.total >= score_min.total


# ── D3: Required step preference ──────────────────────────────────


class TestRequiredStepPreference:
    def test_cleanup_capitalize_requires_normalize(self) -> None:
        """For 'clean up and capitalize', normalize+title_case > title_case alone."""
        good = _make_ir(
            "clean capitalize",
            [("normalize", "text.normalize.v1"), ("title", "text.title_case.v1")],
            {"titled": ("title", "titled")},
            sources={
                "normalize": {"text": ("input", "text")},
                "title": {"text": ("normalize", "normalized")},
            },
        )
        bad = _make_ir(
            "clean capitalize",
            [("title", "text.title_case.v1")],
            {"titled": ("title", "titled")},
        )
        goal = "clean up this text and capitalize each word"
        assert score_candidate(good, goal).total > score_candidate(bad, goal).total

    def test_missing_normalize_penalized(self) -> None:
        bad = _make_ir(
            "tidy up",
            [("extract", "text.extract_keywords.v1")],
            {"keywords": ("extract", "keywords")},
        )
        score = score_candidate(bad, "tidy up this text and find topics")
        penalty_reasons = [r for r, _ in score.penalties]
        assert any("missing_required_skill" in r and "normalize" in r for r in penalty_reasons)


# ── D4: Wrong skill family penalty ────────────────────────────────


class TestWrongSkillFamilyPenalty:
    def test_json_skill_for_text_goal_penalized(self) -> None:
        bad = _make_ir(
            "extract keywords",
            [("extract", "text.extract_keywords.v1"), ("junk", "json.extract_field.v1")],
            {"keywords": ("extract", "keywords")},
            sources={
                "extract": {"text": ("input", "text")},
                "junk": {"raw_json": ("extract", "keywords")},
            },
        )
        score = score_candidate(bad, "extract keywords from this text")
        penalty_reasons = [r for r, _ in score.penalties]
        assert any("wrong_skill_family" in r for r in penalty_reasons)

    def test_json_skill_for_json_goal_not_penalized(self) -> None:
        good = _make_ir(
            "reshape json",
            [("reshape", "json.reshape.v1")],
            {"selected": ("reshape", "selected")},
            sources={"reshape": {"raw_json": ("input", "text")}},
        )
        score = score_candidate(good, "parse and reshape JSON data")
        penalty_reasons = [r for r, _ in score.penalties]
        assert not any("wrong_skill_family" in r for r in penalty_reasons)


# ── D5: Output endpoint preference ────────────────────────────────


class TestOutputEndpointPreference:
    def test_keywords_outranks_joined_for_extraction(self) -> None:
        """Plain extraction: exposing 'keywords' beats exposing 'joined'."""
        correct = _make_ir(
            "extract keywords",
            [("extract", "text.extract_keywords.v1")],
            {"keywords": ("extract", "keywords")},
        )
        wrong = _make_ir(
            "extract keywords",
            [("extract", "text.extract_keywords.v1"), ("format", "text.join_lines.v1")],
            {"joined": ("format", "joined")},
            sources={
                "extract": {"text": ("input", "text")},
                "format": {"lines": ("extract", "keywords")},
            },
        )
        goal = "extract keywords from this text"
        assert score_candidate(correct, goal).total > score_candidate(wrong, goal).total

    def test_correct_output_name_rewarded(self) -> None:
        ir = _make_ir(
            "extract keywords",
            [("extract", "text.extract_keywords.v1")],
            {"keywords": ("extract", "keywords")},
        )
        score = score_candidate(ir, "extract keywords")
        reward_reasons = [r for r, _ in score.rewards]
        assert any("correct_output_name" in r for r in reward_reasons)

    def test_wrong_output_name_penalized(self) -> None:
        ir = _make_ir(
            "normalize",
            [("normalize", "text.normalize.v1")],
            {"cleaned_text": ("normalize", "normalized")},
        )
        score = score_candidate(ir, "normalize this text")
        penalty_reasons = [r for r, _ in score.penalties]
        assert any("output_name_mismatch" in r for r in penalty_reasons)


# ── D6: Backend integration ───────────────────────────────────────


class TestBackendIntegration:
    def test_single_candidate_unchanged(self) -> None:
        """candidate_count=1 works exactly as before."""
        ir_json = json.dumps({
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "extract", "skill_id": "text.extract_keywords.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"keywords": {"step": "extract", "port": "keywords"}},
            "effects": ["llm_inference"],
        })

        class FixedProvider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                return ir_json

        backend = IRPlannerBackend(FixedProvider(), candidate_count=1)  # type: ignore[arg-type]
        result = backend.compose(PlanRequest(goal="extract keywords", candidates=[]))
        assert result.status == "success"
        assert result.graph is not None

    def test_multi_candidate_selects_best(self) -> None:
        """With 3 candidates, the scorer picks the best one."""
        good_ir = json.dumps({
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "extract", "skill_id": "text.extract_keywords.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"keywords": {"step": "extract", "port": "keywords"}},
            "effects": ["llm_inference"],
        })
        bad_ir = json.dumps({
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "extract", "skill_id": "text.extract_keywords.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}},
                {"name": "format", "skill_id": "text.join_lines.v1",
                 "sources": {"lines": {"step": "extract", "port": "keywords"}}}
            ],
            "final_outputs": {"joined": {"step": "format", "port": "joined"}},
            "effects": ["llm_inference"],
        })

        call_count = 0

        class AlternatingProvider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                nonlocal call_count
                call_count += 1
                # Return bad IR 2 out of 3 times, good IR once
                if call_count % 3 == 2:
                    return good_ir
                return bad_ir

        backend = IRPlannerBackend(AlternatingProvider(), candidate_count=3)  # type: ignore[arg-type]
        result = backend.compose(PlanRequest(goal="extract keywords", candidates=[]))
        assert result.status == "success"
        assert result.graph is not None
        # The good candidate (1 step, keywords output) should win
        assert "keywords" in result.graph.graph.outputs
        assert len(result.graph.graph.nodes) == 1

    def test_all_fail_returns_failure(self) -> None:
        class BadProvider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                return "not json"

        backend = IRPlannerBackend(BadProvider(), candidate_count=3)  # type: ignore[arg-type]
        result = backend.compose(PlanRequest(goal="test", candidates=[]))
        assert result.status == "failure"
        assert any("ir_rerank" in h.node_id for h in result.holes)

    def test_candidates_accessible_after_compose(self) -> None:
        ir_json = json.dumps({
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "extract", "skill_id": "text.extract_keywords.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"keywords": {"step": "extract", "port": "keywords"}},
            "effects": ["llm_inference"],
        })

        class FixedProvider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                return ir_json

        backend = IRPlannerBackend(FixedProvider(), candidate_count=3)  # type: ignore[arg-type]
        backend.compose(PlanRequest(goal="extract keywords", candidates=[]))
        assert len(backend.last_candidates) == 3
        for c in backend.last_candidates:
            assert c.status == "compiled"
            assert c.score is not None
            assert c.score.total > 0

    def test_reasoning_includes_selection_info(self) -> None:
        ir_json = json.dumps({
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "extract", "skill_id": "text.extract_keywords.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"keywords": {"step": "extract", "port": "keywords"}},
            "effects": ["llm_inference"],
        })

        class FixedProvider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                return ir_json

        backend = IRPlannerBackend(FixedProvider(), candidate_count=3)  # type: ignore[arg-type]
        result = backend.compose(PlanRequest(goal="extract keywords", candidates=[]))
        assert "candidate" in result.reasoning.lower() or "score" in result.reasoning.lower()


# ── Score breakdown structure ──────────────────────────────────────


class TestScoreBreakdown:
    def test_base_score_is_100(self) -> None:
        ir = _make_ir(
            "test",
            [("extract", "text.extract_keywords.v1")],
            {"keywords": ("extract", "keywords")},
        )
        score = score_candidate(ir, "extract keywords")
        assert score.base_score == 100.0

    def test_penalties_reduce_total(self) -> None:
        ir = _make_ir(
            "test",
            [("extract", "text.extract_keywords.v1"), ("format", "text.join_lines.v1")],
            {"joined": ("format", "joined")},
            sources={
                "extract": {"text": ("input", "text")},
                "format": {"lines": ("extract", "keywords")},
            },
        )
        score = score_candidate(ir, "extract keywords")
        assert score.total < score.base_score
        assert len(score.penalties) > 0

    def test_rewards_increase_total(self) -> None:
        ir = _make_ir(
            "test",
            [("extract", "text.extract_keywords.v1")],
            {"keywords": ("extract", "keywords")},
        )
        score = score_candidate(ir, "extract keywords")
        assert len(score.rewards) > 0
