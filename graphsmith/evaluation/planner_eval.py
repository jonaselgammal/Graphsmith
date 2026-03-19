"""Planner evaluation runner — measures plan quality against known goals."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from graphsmith.exceptions import ValidationError
from graphsmith.planner.backend import PlannerBackend
from graphsmith.planner.candidates import (
    RETRIEVAL_MODES,
    RetrievalDiagnostics,
    retrieve_candidates_with_diagnostics,
)
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.planner.models import PlanResult
from graphsmith.registry.local import LocalRegistry
from graphsmith.validator import validate_skill_package


class EvalGoal(BaseModel):
    """One evaluation goal with expected plan properties."""

    goal: str
    expected_skills: list[str] = Field(default_factory=list)
    expected_output_names: list[str] = Field(default_factory=list)
    acceptable_output_names: list[list[str]] = Field(default_factory=list)
    min_nodes: int = 1
    required_effects: list[str] = Field(default_factory=list)


class EvalChecks(BaseModel):
    """Individual check results for one goal."""

    parsed: bool = False
    has_graph: bool = False
    validates: bool = False
    correct_skills: bool = False
    correct_outputs: bool = False
    min_nodes_met: bool = False
    no_holes: bool = False


class EvalResult(BaseModel):
    """Evaluation result for one goal."""

    goal: str
    status: str = "fail"
    failure_type: str = ""  # "planner", "retrieval", "provider", or "" if pass
    checks: EvalChecks = Field(default_factory=EvalChecks)
    score: float = 0.0
    plan_status: str = ""
    holes: list[str] = Field(default_factory=list)
    error: str = ""
    retrieval: RetrievalDiagnostics | None = None
    expected_skills_in_shortlist: bool = False
    plan_json: dict[str, Any] | None = None


class EvalReport(BaseModel):
    """Full evaluation report."""

    provider: str = ""
    model: str = ""
    retrieval_mode: str = "ranked"
    timestamp: str = ""
    goals_total: int = 0
    goals_passed: int = 0
    pass_rate: float = 0.0
    avg_candidates: float = 0.0
    results: list[EvalResult] = Field(default_factory=list)


def load_goals(goals_dir: str | Path) -> list[EvalGoal]:
    """Load all goal JSON files from a directory."""
    d = Path(goals_dir)
    goals: list[EvalGoal] = []
    for p in sorted(d.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        goals.append(EvalGoal.model_validate(data))
    return goals


def evaluate_goal(
    eval_goal: EvalGoal,
    registry: LocalRegistry,
    backend: PlannerBackend,
    *,
    retrieval_mode: str = "ranked",
) -> EvalResult:
    """Evaluate the planner on a single goal with retrieval diagnostics."""
    from graphsmith.planner.composer import _validate_glue_graph
    from graphsmith.planner.models import PlanRequest, PlanResult as PR

    checks = EvalChecks()
    result_obj = EvalResult(goal=eval_goal.goal)

    # 1. Retrieve candidates with diagnostics
    diag, candidates = retrieve_candidates_with_diagnostics(
        eval_goal.goal, registry, mode=retrieval_mode,
    )
    result_obj.retrieval = diag

    # Check if expected skills are in shortlist
    cand_ids = {c.id for c in candidates}
    if eval_goal.expected_skills:
        result_obj.expected_skills_in_shortlist = all(
            s in cand_ids for s in eval_goal.expected_skills
        )
    else:
        result_obj.expected_skills_in_shortlist = True

    # 2. Plan using the retrieved candidates
    request = PlanRequest(goal=eval_goal.goal, candidates=candidates)
    try:
        plan_result = backend.compose(request)
        plan_result.candidates_considered = [
            f"{c.id}@{c.version}" for c in candidates
        ]
        # Validate if graph present
        if plan_result.graph is not None:
            plan_result = _validate_glue_graph(plan_result)
    except Exception as exc:
        result_obj.error = str(exc)
        result_obj.status = "fail"
        result_obj.failure_type = "provider"
        return result_obj

    # Check if plan_result itself reports a provider error
    _provider_signals = ["provider", "rate limit", "429", "credit balance",
                         "api key", "authentication", "unauthorized", "api error"]
    if plan_result.status == "failure" and any(
        any(sig in h.lower() for sig in _provider_signals)
        for h in [h_obj.description for h_obj in plan_result.holes]
    ):
        result_obj.plan_status = plan_result.status
        result_obj.holes = [h.description for h in plan_result.holes]
        result_obj.error = plan_result.reasoning
        result_obj.status = "fail"
        result_obj.failure_type = "provider"
        return result_obj

    result_obj.plan_status = plan_result.status
    result_obj.holes = [h.description for h in plan_result.holes]

    # Capture the raw plan for artifact saving
    if plan_result.graph is not None:
        result_obj.plan_json = plan_result.graph.model_dump()

    # 3. Checks
    checks.parsed = plan_result.status != "failure"
    checks.has_graph = plan_result.graph is not None

    if not checks.has_graph:
        result_obj.checks = checks
        result_obj.score = _score(checks)
        result_obj.status = "fail"
        return result_obj

    graph = plan_result.graph

    try:
        pkg = glue_to_skill_package(graph)
        validate_skill_package(pkg)
        checks.validates = True
    except (ValidationError, Exception) as exc:
        result_obj.error = str(exc)

    node_skills = set()
    for node in graph.graph.nodes:
        sid = node.config.get("skill_id", "")
        if sid:
            node_skills.add(sid)
    if eval_goal.expected_skills:
        checks.correct_skills = all(
            s in node_skills for s in eval_goal.expected_skills
        )
    else:
        checks.correct_skills = True

    mapped_outputs = set(graph.graph.outputs.keys())
    if eval_goal.acceptable_output_names:
        checks.correct_outputs = all(
            any(name in mapped_outputs for name in alternatives)
            for alternatives in eval_goal.acceptable_output_names
        )
    elif eval_goal.expected_output_names:
        checks.correct_outputs = all(
            name in mapped_outputs for name in eval_goal.expected_output_names
        )
    else:
        checks.correct_outputs = True

    checks.min_nodes_met = len(graph.graph.nodes) >= eval_goal.min_nodes
    checks.no_holes = len(plan_result.holes) == 0

    result_obj.checks = checks
    result_obj.score = _score(checks)
    result_obj.status = (
        "pass" if result_obj.score == 1.0
        else "partial" if result_obj.score > 0
        else "fail"
    )

    # Classify failure type
    if result_obj.status != "pass":
        result_obj.failure_type = _classify_failure(result_obj)

    return result_obj


def run_evaluation(
    goals: list[EvalGoal],
    registry: LocalRegistry,
    backend: PlannerBackend,
    *,
    provider_name: str = "",
    model_name: str = "",
    retrieval_mode: str = "ranked",
    delay_seconds: float = 0.0,
) -> EvalReport:
    """Run evaluation across all goals and produce a report."""
    results: list[EvalResult] = []
    for i, g in enumerate(goals):
        if delay_seconds > 0 and i > 0:
            time.sleep(delay_seconds)
        r = evaluate_goal(g, registry, backend, retrieval_mode=retrieval_mode)
        results.append(r)

    passed = sum(1 for r in results if r.status == "pass")
    total = len(results)
    avg_cands = (
        sum(r.retrieval.candidate_count for r in results if r.retrieval) / total
        if total > 0 else 0.0
    )

    return EvalReport(
        provider=provider_name,
        model=model_name,
        retrieval_mode=retrieval_mode,
        timestamp=datetime.now(timezone.utc).isoformat(),
        goals_total=total,
        goals_passed=passed,
        pass_rate=passed / total if total > 0 else 0.0,
        avg_candidates=round(avg_cands, 1),
        results=results,
    )


def compare_retrieval_modes(
    goals: list[EvalGoal],
    registry: LocalRegistry,
    backend: PlannerBackend,
    *,
    provider_name: str = "",
    model_name: str = "",
    modes: list[str] | None = None,
    delay_seconds: float = 0.0,
    mode_delay_seconds: float = 5.0,
) -> dict[str, EvalReport]:
    """Run evaluation across multiple retrieval modes for comparison.

    mode_delay_seconds: pause between modes to avoid rate limits.
    delay_seconds: pause between individual goals.
    """
    modes = modes or list(RETRIEVAL_MODES)
    reports: dict[str, EvalReport] = {}
    for i, mode in enumerate(modes):
        if i > 0 and mode_delay_seconds > 0:
            time.sleep(mode_delay_seconds)
        reports[mode] = run_evaluation(
            goals, registry, backend,
            provider_name=provider_name,
            model_name=model_name,
            retrieval_mode=mode,
            delay_seconds=delay_seconds,
        )
    return reports


def _classify_failure(result: EvalResult) -> str:
    """Classify a non-pass result as provider, retrieval, or planner failure."""
    # Provider errors
    _sigs = ["429", "rate limit", "provider error", "api error",
             "credit balance", "api key", "authentication",
             "unauthorized", "forbidden", "connect", "timeout"]
    error_lower = result.error.lower()
    if any(s in error_lower for s in _sigs):
        return "provider"
    for hole in result.holes:
        if any(s in hole.lower() for s in _sigs):
            return "provider"

    # Retrieval failures
    if not result.expected_skills_in_shortlist:
        return "retrieval"

    # Everything else is a planner failure
    return "planner"


def _score(checks: EvalChecks) -> float:
    fields = [
        checks.parsed, checks.has_graph, checks.validates,
        checks.correct_skills, checks.correct_outputs,
        checks.min_nodes_met, checks.no_holes,
    ]
    return sum(fields) / len(fields)
