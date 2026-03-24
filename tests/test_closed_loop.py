"""Tests for closed-loop missing-skill generation and replanning."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

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

    def test_skill_already_available_not_missing(self) -> None:
        result = PlanResult(status="failure")
        d = detect_missing_skill(
            "compute the median of numbers",
            result,
            [],
            available_skill_ids={"math.median.v1"},
        )
        assert not d.is_missing
        assert "already exists" in d.reason
        assert d.reusable_existing_skill
        assert d.exact_skill_id == "math.median.v1"


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
        from graphsmith.registry.local import LocalRegistry

        exclude = exclude_skills or set()
        reg_dir = tempfile.mkdtemp()
        reg = LocalRegistry(reg_dir)
        skills_dir = Path(__file__).resolve().parents[1] / "examples" / "skills"
        for d in sorted(skills_dir.iterdir()):
            if d.is_dir() and (d / "skill.yaml").exists():
                if d.name not in exclude:
                    try:
                        reg.publish(str(d))
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
        assert result.stopped_reason == "replan_succeeded"
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
        assert result.stopped_reason == "confirmation_declined"
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
        assert result.stopped_reason == "awaiting_confirmation"
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
        assert result.stopped_reason == "missing_skill_not_detected"
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
        assert result.stopped_reason == "initial_plan_succeeded"
        assert result.success
        assert not result.detected_missing

    def test_existing_exact_skill_gets_one_targeted_replan(self) -> None:
        from graphsmith.registry.local import LocalRegistry
        from graphsmith.skills.autogen import (
            generate_skill_files,
            register_generated_op,
            unregister_generated_op,
        )

        class RetryWithExistingSkillBackend:
            _candidate_count = 1
            _use_decomposition = False
            _last_candidates: list[CandidateResult] = []
            _last_decomposition = None

            def __init__(self) -> None:
                self.calls = 0

            @property
            def last_candidates(self):
                return self._last_candidates

            @property
            def last_decomposition(self):
                return self._last_decomposition

            def compose(self, request):
                self.calls += 1
                if self.calls == 1:
                    return PlanResult(status="failure")
                assert request.candidates
                assert request.candidates[0].id == "math.median.v1"
                return PlanResult(status="success", graph=MagicMock(spec=GlueGraph))

        with tempfile.TemporaryDirectory() as tmpdir:
            reg = LocalRegistry(tmpdir)
            spec = extract_spec("compute the median")
            skill_dir = generate_skill_files(spec, Path(tmpdir) / "gen")
            register_generated_op(spec)
            try:
                reg.publish(skill_dir)
                backend = RetryWithExistingSkillBackend()

                result = run_closed_loop(
                    "compute the median of numbers",
                    backend,
                    reg,
                    auto_approve=True,
                )
            finally:
                unregister_generated_op(spec)

        assert result.stopped_reason == "existing_skill_replan_succeeded"
        assert result.replan_status == "success"
        assert result.success

    def test_single_skill_fallback_after_replan_failure(self) -> None:
        class AlwaysFailBackend:
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
                return PlanResult(status="failure")

        reg, _ = self._make_registry_without()
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_closed_loop(
                "compute the median of numbers",
                AlwaysFailBackend(),
                reg,
                output_dir=tmpdir,
                auto_approve=True,
            )

        assert result.success
        assert result.stopped_reason == "single_skill_fallback_succeeded"
        assert result.replan_plan is not None
        assert result.replan_plan.graph.nodes[0].config["skill_id"] == "math.median.v1"

    def test_multi_stage_fallback_after_replan_failure(self) -> None:
        class AlwaysFailBackend:
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
                return PlanResult(status="failure")

        reg, _ = self._make_registry_without({"text.uppercase.v1"})
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_closed_loop(
                "Normalize this text and then convert it to uppercase",
                AlwaysFailBackend(),
                reg,
                output_dir=tmpdir,
                auto_approve=True,
            )

        assert result.success
        assert result.stopped_reason == "multi_stage_fallback_succeeded"
        assert result.replan_plan is not None
        assert [node.config["skill_id"] for node in result.replan_plan.graph.nodes] == [
            "text.normalize.v1",
            "text.uppercase.v1",
        ]

    def test_multi_stage_fallback_stays_off_for_non_text_chain(self) -> None:
        class AlwaysFailBackend:
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
                return PlanResult(status="failure")

        reg, _ = self._make_registry_without({"math.median.v1"})
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_closed_loop(
                "Compute the median and then pretty print it as json",
                AlwaysFailBackend(),
                reg,
                output_dir=tmpdir,
                auto_approve=True,
            )

        assert not result.success
        assert result.stopped_reason == "replan_failed"

    def test_multi_stage_fallback_handles_generated_predicate_input(self) -> None:
        class AlwaysFailBackend:
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
                return PlanResult(status="failure")

        reg, _ = self._make_registry_without({"text.contains.v1"})
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_closed_loop(
                "Normalize this text, summarize it, and check whether the summary contains a phrase",
                AlwaysFailBackend(),
                reg,
                output_dir=tmpdir,
                auto_approve=True,
            )

        assert result.success
        assert result.stopped_reason == "multi_stage_fallback_succeeded"
        assert result.replan_plan is not None
        assert [node.config["skill_id"] for node in result.replan_plan.graph.nodes] == [
            "text.normalize.v1",
            "text.summarize.v1",
            "text.contains.v1",
        ]
        assert any(edge.to == "step_3.substring" and edge.from_ == "input.substring" for edge in result.replan_plan.graph.edges)


# ── Format output ────────────────────────────────────────────────


class TestFormatClosedLoopResult:
    def test_format_success(self) -> None:
        r = ClosedLoopResult(
            initial_status="failure", detected_missing=True,
            diagnosis_reason="missing math.median.v1",
            validation_pass=True, examples_total=2, examples_passed=2,
            replan_status="success", stopped_reason="replan_succeeded", success=True,
        )
        text = format_closed_loop_result(r)
        assert "SUCCESS" in text
        assert "failure" in text
        assert "success" in text
        assert "Stopped:" in text

    def test_format_failure(self) -> None:
        r = ClosedLoopResult(
            initial_status="failure", detected_missing=False,
            diagnosis_reason="no match", success=False,
        )
        text = format_closed_loop_result(r)
        assert "FAILED" in text

    def test_format_includes_failure_stage(self) -> None:
        r = ClosedLoopResult(
            initial_status="failure",
            detected_missing=True,
            generated_spec=extract_spec("uppercase text"),
            validation_pass=False,
            examples_total=0,
            examples_passed=0,
            generation_failure_stage="validation",
            generation_errors=["Validation: bad package"],
            stopped_reason="generated_skill_validation_failed",
            success=False,
        )
        text = format_closed_loop_result(r)
        assert "Failure stage: validation" in text
        assert "generated_skill_validation_failed" in text


class TestClosedLoopCli:
    def test_solve_with_echo_provider_shows_generation_and_stop_reason(self) -> None:
        from graphsmith.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, [
            "solve",
            "compute the median of numbers",
            "--provider", "echo",
            "--auto-approve",
        ])

        assert result.exit_code == 0
        assert "Closed-Loop Result" in result.output
        assert "Generated: math.median.v1" in result.output
        assert "Validation: PASS" in result.output
        assert "Stopped: single_skill_fallback_succeeded" in result.output
