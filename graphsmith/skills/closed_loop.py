"""Closed-loop planning: detect missing skill → generate → validate → replan.

Bounded prototype that handles exactly one missing deterministic single-step skill.
"""
from __future__ import annotations

import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from graphsmith.planner.ir_backend import CandidateResult
from graphsmith.planner.models import GlueGraph, PlanRequest, PlanResult
from graphsmith.registry.local import LocalRegistry
from graphsmith.skills.autogen import (
    AutogenError,
    SkillSpec,
    extract_spec,
    format_result,
    generate_skill_files,
    register_generated_op,
    unregister_generated_op,
    validate_and_test,
)
from graphsmith.registry.index import IndexEntry


# ── Missing-skill detection ──────────────────────────────────────


class MissingSkillDiagnosis(BaseModel):
    """Structured result of missing-skill analysis."""

    is_missing: bool = False
    reason: str = ""
    capability_hint: str = ""  # natural language description for autogen
    exact_skill_id: str = ""
    reusable_existing_skill: bool = False


def detect_missing_skill(
    goal: str,
    result: PlanResult,
    candidates: list[CandidateResult],
    *,
    available_skill_ids: set[str] | None = None,
) -> MissingSkillDiagnosis:
    """Analyze a failed plan to determine if a missing skill is the cause.

    Detection heuristics (narrow and explicit):
    1. All candidates failed (no valid plan produced)
    2. Goal keywords suggest a simple deterministic op
    3. The op is matchable by the autogen template catalog
    """
    # If planning succeeded, no missing skill
    if result.status == "success" and result.graph is not None:
        return MissingSkillDiagnosis(is_missing=False, reason="Plan succeeded")

    # Try to extract an autogen spec — if it matches, the skill might be missing
    try:
        spec = extract_spec(goal)
    except AutogenError:
        # Goal doesn't match any autogen template → not a missing-skill case
        return MissingSkillDiagnosis(
            is_missing=False,
            reason="Goal does not match any generatable skill template",
        )

    available = available_skill_ids or set()
    if spec.skill_id in available:
        return MissingSkillDiagnosis(
            is_missing=False,
            reason=f"Skill {spec.skill_id} already exists in the registry/candidate set",
            exact_skill_id=spec.skill_id,
            reusable_existing_skill=True,
        )

    # Check if the matching skill already exists in the candidate plan
    compiled = [c for c in candidates if c.status == "compiled" and c.ir]
    if compiled:
        used_skills = set()
        for c in compiled:
            for step in c.ir.steps:
                used_skills.add(step.skill_id)
        # If the exact skill is already used, the problem is elsewhere
        if spec.skill_id in used_skills:
            return MissingSkillDiagnosis(
                is_missing=False,
                reason=f"Skill {spec.skill_id} was already used in candidates",
                exact_skill_id=spec.skill_id,
            )

    # All candidates failed or none used the right skill
    return MissingSkillDiagnosis(
        is_missing=True,
        reason=f"No candidate used {spec.skill_id} and goal matches template '{spec.template_key}'",
        capability_hint=goal,
        exact_skill_id=spec.skill_id,
    )


def _find_registry_entry_by_id(
    registry: LocalRegistry, skill_id: str,
) -> IndexEntry | None:
    if not hasattr(registry, "list_all"):
        return None
    try:
        for entry in registry.list_all():
            if entry.id == skill_id:
                return entry
    except Exception:
        return None
    return None


def _prepend_exact_skill_candidate(
    candidates: Sequence[IndexEntry],
    registry: LocalRegistry,
    skill_id: str,
) -> list[IndexEntry]:
    """Prepend an exact matching skill candidate if it exists in the registry."""
    exact = _find_registry_entry_by_id(registry, skill_id)
    if exact is None:
        return list(candidates)
    out = [exact]
    out.extend(entry for entry in candidates if entry.id != skill_id)
    return out


# ── Closed-loop result ───────────────────────────────────────────


class ClosedLoopResult(BaseModel):
    """Complete result of a closed-loop planning attempt."""

    # Initial attempt
    initial_status: str = ""
    initial_plan: GlueGraph | None = None

    # Missing skill detection
    detected_missing: bool = False
    diagnosis_reason: str = ""

    # Skill generation
    generated_spec: SkillSpec | None = None
    generation_dir: str = ""
    validation_pass: bool = False
    examples_total: int = 0
    examples_passed: int = 0
    generation_failure_stage: str = ""
    generation_errors: list[str] = Field(default_factory=list)

    # Replan
    replan_status: str = ""
    replan_plan: GlueGraph | None = None

    # Overall
    stopped_reason: str = ""
    success: bool = False


def _is_multi_stage_goal(goal: str) -> bool:
    goal_lower = goal.lower()
    return any(
        token in goal_lower
        for token in (" and ", " then ", " after ", " before ", " both ", " for each ", " each ")
    )


def _build_single_skill_plan(goal: str, spec: SkillSpec) -> GlueGraph:
    """Build a deterministic one-node plan for a generated skill."""
    from graphsmith.models.common import IOField
    from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode

    return GlueGraph(
        goal=goal,
        inputs=[IOField(name=inp["name"], type=inp["type"]) for inp in spec.inputs],
        outputs=[IOField(name=out["name"], type=out["type"]) for out in spec.outputs],
        effects=["pure"],
        graph=GraphBody(
            version=1,
            nodes=[GraphNode(id="generated", op="skill.invoke", config={"skill_id": spec.skill_id})],
            edges=[
                GraphEdge(from_=f"input.{inp['name']}", to=f"generated.{inp['name']}")
                for inp in spec.inputs
            ],
            outputs={out["name"]: f"generated.{out['name']}" for out in spec.outputs},
        ),
    )


# ── Orchestrator ─────────────────────────────────────────────────


def run_closed_loop(
    goal: str,
    backend: Any,
    registry: LocalRegistry,
    *,
    output_dir: str | Path | None = None,
    auto_approve: bool = False,
    confirm_fn: Any = None,
) -> ClosedLoopResult:
    """Run one closed-loop attempt: plan → detect → generate → replan.

    Args:
        goal: Natural language goal
        backend: IR planner backend
        registry: Skill registry
        output_dir: Where to generate skill files (default: temp dir)
        auto_approve: Skip user confirmation for replan
        confirm_fn: Callable(str) → bool for interactive confirmation
    """
    from graphsmith.planner.candidates import retrieve_candidates

    result = ClosedLoopResult()
    generated_registered = False

    # ── Step 1: Initial plan attempt ──────────────────────────────
    exact_spec: SkillSpec | None = None
    try:
        exact_spec = extract_spec(goal)
    except AutogenError:
        exact_spec = None

    cands = retrieve_candidates(goal, registry)
    if exact_spec is not None:
        cands = _prepend_exact_skill_candidate(cands, registry, exact_spec.skill_id)
    request = PlanRequest(goal=goal, candidates=cands)
    plan_result = backend.compose(request)

    result.initial_status = plan_result.status
    result.initial_plan = plan_result.graph

    if plan_result.status == "success" and plan_result.graph is not None:
        result.stopped_reason = "initial_plan_succeeded"
        result.success = True
        return result

    # ── Step 2: Detect missing skill ──────────────────────────────
    diagnosis = detect_missing_skill(goal, plan_result, backend.last_candidates)
    available_ids = {f"{entry.id}" for entry in cands}
    if hasattr(registry, "list_all"):
        try:
            available_ids.update(entry.id for entry in registry.list_all())
        except Exception:
            pass
    diagnosis = detect_missing_skill(
        goal,
        plan_result,
        backend.last_candidates,
        available_skill_ids=available_ids,
    )
    result.detected_missing = diagnosis.is_missing
    result.diagnosis_reason = diagnosis.reason

    if diagnosis.reusable_existing_skill and diagnosis.exact_skill_id:
        cands = retrieve_candidates(goal, registry)
        cands = _prepend_exact_skill_candidate(cands, registry, diagnosis.exact_skill_id)
        retry_request = PlanRequest(goal=goal, candidates=cands)
        retry_result = backend.compose(retry_request)
        result.replan_status = retry_result.status
        result.replan_plan = retry_result.graph
        if retry_result.status == "success" and retry_result.graph is not None:
            result.stopped_reason = "existing_skill_replan_succeeded"
            result.success = True
            return result
        if exact_spec is not None and not _is_multi_stage_goal(goal):
            result.replan_status = "success"
            result.replan_plan = _build_single_skill_plan(goal, exact_spec)
            result.stopped_reason = "single_skill_fallback_succeeded"
            result.success = True
            return result
        result.stopped_reason = "existing_skill_replan_failed"
        return result

    if not diagnosis.is_missing:
        result.stopped_reason = "missing_skill_not_detected"
        return result

    # ── Step 3: Generate candidate skill ──────────────────────────
    try:
        spec = extract_spec(diagnosis.capability_hint)
    except AutogenError as exc:
        result.stopped_reason = "spec_extraction_failed"
        result.generation_errors.append(str(exc))
        return result

    result.generated_spec = spec

    gen_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp()) / "generated_skills"
    gen_dir.mkdir(parents=True, exist_ok=True)

    skill_dir = generate_skill_files(spec, gen_dir)
    result.generation_dir = str(skill_dir)

    # ── Step 4: Validate + test ───────────────────────────────────
    val_result = validate_and_test(spec, skill_dir)
    result.validation_pass = val_result["validation"] == "PASS"
    result.examples_total = val_result["examples_total"]
    result.examples_passed = val_result["examples_passed"]
    result.generation_failure_stage = val_result.get("failure_stage", "")
    result.generation_errors = val_result["errors"]

    if not result.validation_pass:
        result.stopped_reason = "generated_skill_validation_failed"
        return result
    if result.examples_passed < result.examples_total:
        result.stopped_reason = "generated_skill_examples_failed"
        return result

    # ── Step 5: Confirm with user ─────────────────────────────────
    if not auto_approve:
        if confirm_fn is None:
            result.stopped_reason = "awaiting_confirmation"
            return result  # no way to confirm → return for caller to handle
        summary = (
            f"Generated skill {spec.skill_id} "
            f"(validation PASS, examples {result.examples_passed}/{result.examples_total} PASS). "
            f"Replan with this skill?"
        )
        if not confirm_fn(summary):
            result.stopped_reason = "confirmation_declined"
            return result

    # ── Step 6: Publish to registry + replan ──────────────────────
    try:
        register_generated_op(spec)
        generated_registered = True
        registry.publish(str(skill_dir))
    except Exception as exc:
        result.stopped_reason = "publish_failed"
        result.generation_errors.append(f"Publish failed: {exc}")
        return result

    try:
        cands = retrieve_candidates(goal, registry)
        cands = _prepend_exact_skill_candidate(cands, registry, spec.skill_id)
        request = PlanRequest(goal=goal, candidates=cands)
        replan_result = backend.compose(request)

        result.replan_status = replan_result.status
        result.replan_plan = replan_result.graph
        result.success = replan_result.status == "success" and replan_result.graph is not None
        if result.success:
            result.stopped_reason = "replan_succeeded"
            return result
        if not _is_multi_stage_goal(goal):
            result.replan_status = "success"
            result.replan_plan = _build_single_skill_plan(goal, spec)
            result.stopped_reason = "single_skill_fallback_succeeded"
            result.success = True
            return result
        result.stopped_reason = "replan_failed"
        return result
    finally:
        if generated_registered:
            unregister_generated_op(spec)


# ── Display helpers ──────────────────────────────────────────────


def format_closed_loop_result(result: ClosedLoopResult) -> str:
    """Format a ClosedLoopResult for human display."""
    lines: list[str] = []

    lines.append("  Closed-Loop Result")
    lines.append("  " + "-" * 40)

    # Initial
    lines.append(f"  Initial plan: {result.initial_status}")

    # Detection
    if result.detected_missing:
        lines.append(f"  Missing skill detected: {result.diagnosis_reason}")
    else:
        if result.initial_status != "success":
            lines.append(f"  No missing skill detected: {result.diagnosis_reason}")

    # Generation
    if result.generated_spec:
        spec = result.generated_spec
        lines.append(f"  Generated: {spec.skill_id} ({spec.family})")
        lines.append(f"  Validation: {'PASS' if result.validation_pass else 'FAIL'}")
        lines.append(f"  Examples: {result.examples_passed}/{result.examples_total} PASS")
        if result.generation_failure_stage:
            lines.append(f"  Failure stage: {result.generation_failure_stage}")
        if result.generation_dir:
            lines.append(f"  Files: {result.generation_dir}")

    # Replan
    if result.replan_status:
        lines.append(f"  Replan: {result.replan_status}")

    # Plan delta
    if result.replan_plan and result.initial_plan is None:
        lines.append("")
        lines.append("  Plan delta:")
        lines.append("    Before: (no valid plan)")
        chain = " \u2192 ".join(n.id for n in result.replan_plan.graph.nodes)
        outputs = ", ".join(result.replan_plan.graph.outputs.keys())
        lines.append(f"    After: {chain}")
        lines.append(f"    Outputs: {outputs}")

    # Errors
    if result.generation_errors:
        lines.append("  Errors:")
        for err in result.generation_errors[:3]:
            lines.append(f"    - {err[:80]}")

    if result.stopped_reason:
        lines.append(f"  Stopped: {result.stopped_reason}")

    # Overall
    status = "\u2714 SUCCESS" if result.success else "\u2716 FAILED"
    lines.append(f"\n  {status}")

    return "\n".join(lines)
