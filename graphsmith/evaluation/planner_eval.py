"""Planner evaluation runner — measures plan quality against known goals."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from graphsmith.exceptions import ValidationError
from graphsmith.planner.backend import PlannerBackend
from graphsmith.planner.composer import compose_plan, glue_to_skill_package
from graphsmith.planner.models import PlanResult
from graphsmith.registry.local import LocalRegistry
from graphsmith.validator import validate_skill_package


class EvalGoal(BaseModel):
    """One evaluation goal with expected plan properties."""

    goal: str
    expected_skills: list[str] = Field(default_factory=list)
    expected_output_names: list[str] = Field(default_factory=list)
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
    status: str = "fail"  # "pass", "partial", "fail"
    checks: EvalChecks = Field(default_factory=EvalChecks)
    score: float = 0.0
    plan_status: str = ""
    holes: list[str] = Field(default_factory=list)
    error: str = ""


class EvalReport(BaseModel):
    """Full evaluation report."""

    provider: str = ""
    model: str = ""
    timestamp: str = ""
    goals_total: int = 0
    goals_passed: int = 0
    pass_rate: float = 0.0
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
) -> EvalResult:
    """Evaluate the planner on a single goal."""
    checks = EvalChecks()
    result_obj = EvalResult(goal=eval_goal.goal)

    # 1. Plan
    try:
        plan_result = compose_plan(eval_goal.goal, registry, backend)
    except Exception as exc:
        result_obj.error = str(exc)
        result_obj.status = "fail"
        return result_obj

    result_obj.plan_status = plan_result.status
    result_obj.holes = [h.description for h in plan_result.holes]

    # 2. Check: parsed
    checks.parsed = plan_result.status != "failure"

    # 3. Check: has_graph
    checks.has_graph = plan_result.graph is not None

    if not checks.has_graph:
        result_obj.checks = checks
        result_obj.score = _score(checks)
        result_obj.status = "fail"
        return result_obj

    graph = plan_result.graph

    # 4. Check: validates
    try:
        pkg = glue_to_skill_package(graph)
        validate_skill_package(pkg)
        checks.validates = True
    except (ValidationError, Exception) as exc:
        result_obj.error = str(exc)

    # 5. Check: correct_skills
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

    # 6. Check: correct_outputs
    mapped_outputs = set(graph.graph.outputs.keys())
    if eval_goal.expected_output_names:
        checks.correct_outputs = all(
            name in mapped_outputs for name in eval_goal.expected_output_names
        )
    else:
        checks.correct_outputs = True

    # 7. Check: min_nodes
    checks.min_nodes_met = len(graph.graph.nodes) >= eval_goal.min_nodes

    # 8. Check: no_holes
    checks.no_holes = len(plan_result.holes) == 0

    result_obj.checks = checks
    result_obj.score = _score(checks)
    result_obj.status = "pass" if result_obj.score == 1.0 else "partial" if result_obj.score > 0 else "fail"
    return result_obj


def run_evaluation(
    goals: list[EvalGoal],
    registry: LocalRegistry,
    backend: PlannerBackend,
    *,
    provider_name: str = "",
    model_name: str = "",
) -> EvalReport:
    """Run evaluation across all goals and produce a report."""
    results: list[EvalResult] = []
    for g in goals:
        r = evaluate_goal(g, registry, backend)
        results.append(r)

    passed = sum(1 for r in results if r.status == "pass")
    total = len(results)

    return EvalReport(
        provider=provider_name,
        model=model_name,
        timestamp=datetime.now(timezone.utc).isoformat(),
        goals_total=total,
        goals_passed=passed,
        pass_rate=passed / total if total > 0 else 0.0,
        results=results,
    )


def _score(checks: EvalChecks) -> float:
    """Compute score as fraction of passed checks."""
    fields = [
        checks.parsed,
        checks.has_graph,
        checks.validates,
        checks.correct_skills,
        checks.correct_outputs,
        checks.min_nodes_met,
        checks.no_holes,
    ]
    return sum(fields) / len(fields)
