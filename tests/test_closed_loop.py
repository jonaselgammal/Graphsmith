"""Tests for closed-loop missing-skill generation and replanning."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from graphsmith.planner.ir_backend import CandidateResult
from graphsmith.planner.models import GlueGraph, PlanResult, UnresolvedHole
from graphsmith.skills.autogen import AutogenError, extract_spec
from graphsmith.skills.closed_loop import (
    ClosedLoopResult,
    MissingSkillDiagnosis,
    detect_missing_skill,
    format_closed_loop_result,
    run_closed_loop,
)


# ── Missing-skill detection ──────────────────────────────────────


class TestDetectMissingSkill:
    def test_success_means_no_missing(self) -> None:
        result = PlanResult(status="success", graph=MagicMock(spec=GlueGraph))
        d = detect_missing_skill("uppercase text", result, [])
        assert not d.is_missing

    def test_failure_with_matching_template(self) -> None:
        result = PlanResult(status="failure")
        d = detect_missing_skill("compute the median of numbers", result, [])
        assert d.is_missing
        assert "median" in d.reason

    def test_failure_without_matching_template(self) -> None:
        result = PlanResult(status="failure")
        d = detect_missing_skill("frobnicate the gizmo", result, [])
        assert not d.is_missing
        assert "does not match" in d.reason

    def test_out_of_scope_not_detected(self) -> None:
        result = PlanResult(status="failure")
        d = detect_missing_skill("fetch data from http API", result, [])
        assert not d.is_missing

    def test_skill_already_used_not_missing(self) -> None:
        """If the matching skill is already in candidates, it's not missing."""
        from graphsmith.planner.ir import IRStep, IRSource, PlanningIR, IRInput
        ir = PlanningIR(
            goal="test", inputs=[IRInput(name="text")],
            steps=[IRStep(name="up", skill_id="text.uppercase.v1",
                          sources={"text": IRSource(step="input", port="text")})],
            final_outputs={},
        )
        cand = CandidateResult(index=0, status="compiled", ir=ir)
        result = PlanResult(status="failure")
        d = detect_missing_skill("uppercase text", result, [cand])
        assert not d.is_missing
        assert "already used" in d.reason


# ── Autogen median template ──────────────────────────────────────


class TestMedianTemplate:
    def test_median_spec_extraction(self) -> None:
        spec = extract_spec("compute the median of numbers")
        assert spec.template_key == "median"
        assert spec.category == "math"

    def test_median_validates_and_passes(self) -> None:
        from graphsmith.skills.autogen import generate_skill_files, validate_and_test
        spec = extract_spec("median of numbers")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            result = validate_and_test(spec, path)
            assert result["validation"] == "PASS"
            assert result["examples_passed"] == result["examples_total"]
            assert result["examples_total"] >= 2


# ── Closed-loop orchestration (deterministic, mock LLM) ──────────


class TestClosedLoopOrchestration:
    """Test the full orchestration with a mock planner backend."""

    def _make_registry_without(self, exclude_skills: set[str] | None = None) -> tuple:
        """Build a registry excluding specific skills."""
        from graphsmith.parser import load_skill_package
        from graphsmith.registry.local import LocalRegistry

        exclude = exclude_skills or set()
        reg_dir = tempfile.mkdtemp()
        reg = LocalRegistry(reg_dir)
        skills_dir = Path(__file__).resolve().parents[1] / "examples" / "skills"
        for d in sorted(skills_dir.iterdir()):
            if d.is_dir() and (d / "skill.yaml").exists():
                if d.name not in exclude:
                    try:
                        reg.publish(load_skill_package(str(d)))
                    except Exception:
                        pass
        return reg, reg_dir

    def test_auto_approve_generates_and_validates(self) -> None:
        """With auto_approve, the loop should generate, validate, and return."""
        # Use a mock backend that always fails initial plan
        class FailThenSucceedBackend:
            _candidate_count = 3
            _use_decomposition = True
            _last_candidates: list[CandidateResult] = []
            _last_decomposition = None
            _call_count = 0

            @property
            def last_candidates(self):
                return self._last_candidates

            @property
            def last_decomposition(self):
                return self._last_decomposition

            def compose(self, request):
                self._call_count += 1
                if self._call_count == 1:
                    # First call: fail
                    self._last_candidates = []
                    return PlanResult(status="failure")
                # Second call: succeed with a mock graph
                from graphsmith.models.common import IOField
                from graphsmith.models.graph import GraphBody, GraphNode, GraphEdge
                glue = GlueGraph(
                    goal=request.goal,
                    inputs=[IOField(name="values", type="string")],
                    outputs=[IOField(name="result", type="string")],
                    effects=["pure"],
                    graph=GraphBody(version=1,
                        nodes=[GraphNode(id="median", op="skill.invoke",
                                         config={"skill_id": "math.median.v1"})],
                        edges=[GraphEdge(from_="input.values", to="median.values")],
                        outputs={"result": "median.result"}),
                )
                self._last_candidates = []
                return PlanResult(status="success", graph=glue)

        reg, _ = self._make_registry_without()
        backend = FailThenSucceedBackend()

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_closed_loop(
                "compute the median of numbers",
                backend, reg,
                output_dir=tmpdir,
                auto_approve=True,
            )

        assert result.detected_missing
        assert result.generated_spec is not None
        assert result.generated_spec.skill_id == "math.median.v1"
        assert result.validation_pass
        assert result.examples_passed == result.examples_total
        assert result.replan_status == "success"
        assert result.success

    def test_user_decline_stops_loop(self) -> None:
        class AlwaysFailBackend:
            _candidate_count = 3
            _use_decomposition = True
            _last_candidates: list[CandidateResult] = []
            _last_decomposition = None

            @property
            def last_candidates(self):
                return self._last_candidates

            @property
            def last_decomposition(self):
                return self._last_decomposition

            def compose(self, request):
                self._last_candidates = []
                return PlanResult(status="failure")

        reg, _ = self._make_registry_without()

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_closed_loop(
                "compute the median of numbers",
                AlwaysFailBackend(), reg,
                output_dir=tmpdir,
                confirm_fn=lambda msg: False,  # user declines
            )

        assert result.detected_missing
        assert result.validation_pass
        assert not result.success  # user declined, no replan
        assert result.replan_status == ""

    def test_no_confirm_fn_returns_without_replan(self) -> None:
        class AlwaysFailBackend:
            _candidate_count = 3
            _use_decomposition = True
            _last_candidates: list[CandidateResult] = []
            _last_decomposition = None

            @property
            def last_candidates(self):
                return self._last_candidates

            @property
            def last_decomposition(self):
                return self._last_decomposition

            def compose(self, request):
                self._last_candidates = []
                return PlanResult(status="failure")

        reg, _ = self._make_registry_without()

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_closed_loop(
                "compute the median of numbers",
                AlwaysFailBackend(), reg,
                output_dir=tmpdir,
                # no confirm_fn, no auto_approve
            )

        assert result.detected_missing
        assert result.validation_pass
        assert not result.success

    def test_unrecognized_goal_no_generation(self) -> None:
        class AlwaysFailBackend:
            _candidate_count = 3
            _use_decomposition = True
            _last_candidates: list[CandidateResult] = []
            _last_decomposition = None

            @property
            def last_candidates(self):
                return self._last_candidates

            @property
            def last_decomposition(self):
                return self._last_decomposition

            def compose(self, request):
                self._last_candidates = []
                return PlanResult(status="failure")

        reg, _ = self._make_registry_without()

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_closed_loop(
                "frobnicate the gizmo",
                AlwaysFailBackend(), reg,
                output_dir=tmpdir,
                auto_approve=True,
            )

        assert not result.detected_missing
        assert result.generated_spec is None
        assert not result.success

    def test_initial_success_skips_loop(self) -> None:
        from graphsmith.models.common import IOField
        from graphsmith.models.graph import GraphBody, GraphNode, GraphEdge

        class SuccessBackend:
            _candidate_count = 1
            _use_decomposition = False
            _last_candidates: list[CandidateResult] = []
            _last_decomposition = None

            @property
            def last_candidates(self):
                return self._last_candidates

            @property
            def last_decomposition(self):
                return self._last_decomposition

            def compose(self, request):
                glue = GlueGraph(
                    goal="test", inputs=[IOField(name="text", type="string")],
                    outputs=[IOField(name="result", type="string")],
                    effects=[], graph=GraphBody(version=1, nodes=[], edges=[], outputs={}),
                )
                return PlanResult(status="success", graph=glue)

        reg, _ = self._make_registry_without()
        result = run_closed_loop("trim text", SuccessBackend(), reg, auto_approve=True)
        assert result.success
        assert not result.detected_missing


# ── Format output ────────────────────────────────────────────────


class TestFormatClosedLoopResult:
    def test_format_success(self) -> None:
        r = ClosedLoopResult(
            initial_status="failure", detected_missing=True,
            diagnosis_reason="missing math.median.v1",
            validation_pass=True, examples_total=2, examples_passed=2,
            replan_status="success", success=True,
        )
        text = format_closed_loop_result(r)
        assert "SUCCESS" in text
        assert "failure" in text
        assert "success" in text

    def test_format_failure(self) -> None:
        r = ClosedLoopResult(
            initial_status="failure", detected_missing=False,
            diagnosis_reason="no match", success=False,
        )
        text = format_closed_loop_result(r)
        assert "FAILED" in text
