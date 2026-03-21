"""Stability evaluation — repeated runs with trace export and aggregation."""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from graphsmith.evaluation.planner_eval import EvalReport, EvalResult


# ── Trace record ───────────────────────────────────────────────────


class TraceRecord(BaseModel):
    """One planning trace for a single goal in a single run."""

    run_index: int
    timestamp: str = ""
    goal: str
    model: str = ""
    backend: str = ""
    candidate_count: int = 1
    use_decomposition: bool = False

    # Decomposition
    decomposition: dict[str, Any] | None = None

    # Candidates
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    winning_candidate_index: int = -1

    # Result
    status: str = ""
    failure_type: str = ""
    failed_checks: list[str] = Field(default_factory=list)
    error: str = ""

    # Compiled graph summary
    graph_nodes: list[str] = Field(default_factory=list)
    graph_outputs: dict[str, str] = Field(default_factory=dict)

    # Labels
    failure_class: str = ""  # wrong_output_name, wrong_skill, over_composition, etc.


class GoalStability(BaseModel):
    """Stability summary for one goal across multiple runs."""

    goal: str
    total_runs: int = 0
    passes: int = 0
    pass_rate: float = 0.0
    stability: str = ""  # "always_pass", "always_fail", "intermittent"
    failure_classes: list[str] = Field(default_factory=list)
    dominant_failure: str = ""


class StabilityReport(BaseModel):
    """Aggregated stability report across multiple runs."""

    model: str = ""
    backend: str = ""
    candidate_count: int = 1
    use_decomposition: bool = False
    num_runs: int = 0
    timestamp: str = ""

    # Aggregate pass rates
    pass_counts: list[int] = Field(default_factory=list)
    pass_rates: list[float] = Field(default_factory=list)
    min_pass_rate: float = 0.0
    max_pass_rate: float = 0.0
    mean_pass_rate: float = 0.0
    median_pass_rate: float = 0.0

    # Per-set breakdown
    set_stats: dict[str, dict[str, float]] = Field(default_factory=dict)

    # Per-goal stability
    goal_stability: list[GoalStability] = Field(default_factory=list)

    # Summary counts
    always_pass: int = 0
    always_fail: int = 0
    intermittent: int = 0


# ── Trace extraction ──────────────────────────────────────────────


def extract_trace(
    result: EvalResult,
    *,
    run_index: int,
    model: str = "",
    backend: str = "",
    candidate_count: int = 1,
    use_decomposition: bool = False,
    ir_backend: Any = None,
) -> TraceRecord:
    """Extract a trace record from an eval result + optional backend state."""
    failed_checks = []
    if result.checks:
        for field in ["parsed", "has_graph", "validates", "correct_skills",
                       "correct_outputs", "min_nodes_met", "no_holes"]:
            if not getattr(result.checks, field, True):
                failed_checks.append(field)

    # Graph summary
    graph_nodes: list[str] = []
    graph_outputs: dict[str, str] = {}
    if result.plan_json:
        g = result.plan_json.get("graph", {})
        for n in g.get("nodes", []):
            sid = n.get("config", {}).get("skill_id", n.get("op", ""))
            graph_nodes.append(f"{n.get('id', '?')}:{sid}")
        graph_outputs = g.get("outputs", {})

    # Decomposition + candidates from IR backend
    decomp_data = None
    cand_data: list[dict[str, Any]] = []
    winning_idx = -1
    if ir_backend is not None:
        d = getattr(ir_backend, "last_decomposition", None)
        if d is not None:
            decomp_data = d.model_dump()
        for c in getattr(ir_backend, "last_candidates", []):
            cd: dict[str, Any] = {
                "index": c.index,
                "status": c.status,
                "error": c.error,
            }
            if c.ir:
                cd["steps"] = [(s.name, s.skill_id) for s in c.ir.steps]
                cd["final_outputs"] = {
                    k: f"{v.step}.{v.port}" for k, v in c.ir.final_outputs.items()
                }
            if c.score:
                cd["score"] = c.score.total
                cd["penalties"] = c.score.penalties
                cd["rewards"] = c.score.rewards
            if c.status == "compiled" and c.glue is not None:
                cd["selected"] = (c.glue.graph.outputs == graph_outputs)
                if cd["selected"]:
                    winning_idx = c.index
            cand_data.append(cd)

    # Failure classification
    failure_class = classify_failure(result)

    return TraceRecord(
        run_index=run_index,
        timestamp=datetime.now(timezone.utc).isoformat(),
        goal=result.goal,
        model=model,
        backend=backend,
        candidate_count=candidate_count,
        use_decomposition=use_decomposition,
        decomposition=decomp_data,
        candidates=cand_data,
        winning_candidate_index=winning_idx,
        status=result.status,
        failure_type=result.failure_type,
        failed_checks=failed_checks,
        error=result.error[:200] if result.error else "",
        graph_nodes=graph_nodes,
        graph_outputs=graph_outputs,
        failure_class=failure_class,
    )


def classify_failure(result: EvalResult) -> str:
    """Classify a failure into a semantic category."""
    if result.status == "pass":
        return ""
    checks = result.checks
    if not checks.parsed or not checks.has_graph:
        if "provider" in (result.error or "").lower():
            return "provider_error"
        return "parse_error"
    if not checks.validates:
        return "validation_error"
    if not checks.correct_skills and not checks.correct_outputs:
        return "wrong_skill_and_output"
    if not checks.correct_skills:
        return "wrong_skill_selection"
    if not checks.correct_outputs:
        return "wrong_output_name"
    if not checks.min_nodes_met:
        return "too_few_nodes"
    if not checks.no_holes:
        return "has_holes"
    return "other"


# ── Trace export ──────────────────────────────────────────────────


def export_traces(traces: list[TraceRecord], path: str | Path) -> None:
    """Export traces as JSONL."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t.model_dump()) + "\n")


def load_traces(path: str | Path) -> list[TraceRecord]:
    """Load traces from JSONL."""
    p = Path(path)
    traces: list[TraceRecord] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            traces.append(TraceRecord.model_validate(json.loads(line)))
    return traces


# ── Stability aggregation ─────────────────────────────────────────


def aggregate_stability(
    reports: list[EvalReport],
    *,
    model: str = "",
    backend: str = "",
    candidate_count: int = 1,
    use_decomposition: bool = False,
    set_labels: list[str] | None = None,
) -> StabilityReport:
    """Aggregate multiple eval reports into a stability summary."""
    num_runs = len(reports)
    if num_runs == 0:
        return StabilityReport()

    pass_counts = [r.goals_passed for r in reports]
    totals = [r.goals_total for r in reports]
    pass_rates = [r.pass_rate for r in reports]

    # Per-goal tracking
    all_goals: dict[str, list[str]] = {}  # goal -> [status per run]
    all_failure_classes: dict[str, list[str]] = {}
    for report in reports:
        for result in report.results:
            if result.goal not in all_goals:
                all_goals[result.goal] = []
                all_failure_classes[result.goal] = []
            all_goals[result.goal].append(result.status)
            if result.status != "pass":
                fc = classify_failure(result)
                all_failure_classes[result.goal].append(fc)

    goal_stability: list[GoalStability] = []
    always_pass = 0
    always_fail = 0
    intermittent = 0

    for goal in sorted(all_goals.keys()):
        statuses = all_goals[goal]
        passes = sum(1 for s in statuses if s == "pass")
        rate = passes / len(statuses) if statuses else 0.0
        fcs = all_failure_classes.get(goal, [])
        dominant = max(set(fcs), key=fcs.count) if fcs else ""

        if passes == len(statuses):
            stability = "always_pass"
            always_pass += 1
        elif passes == 0:
            stability = "always_fail"
            always_fail += 1
        else:
            stability = "intermittent"
            intermittent += 1

        goal_stability.append(GoalStability(
            goal=goal,
            total_runs=len(statuses),
            passes=passes,
            pass_rate=rate,
            stability=stability,
            failure_classes=sorted(set(fcs)),
            dominant_failure=dominant,
        ))

    return StabilityReport(
        model=model,
        backend=backend,
        candidate_count=candidate_count,
        use_decomposition=use_decomposition,
        num_runs=num_runs,
        timestamp=datetime.now(timezone.utc).isoformat(),
        pass_counts=pass_counts,
        pass_rates=pass_rates,
        min_pass_rate=min(pass_rates),
        max_pass_rate=max(pass_rates),
        mean_pass_rate=statistics.mean(pass_rates),
        median_pass_rate=statistics.median(pass_rates),
        goal_stability=goal_stability,
        always_pass=always_pass,
        always_fail=always_fail,
        intermittent=intermittent,
    )


def print_stability_report(report: StabilityReport) -> str:
    """Format a stability report as human-readable text."""
    lines: list[str] = []
    lines.append(f"Stability Report: {report.model} ({report.backend})")
    lines.append(f"  Runs: {report.num_runs}")
    lines.append(f"  Candidates: {report.candidate_count}, Decomposition: {report.use_decomposition}")
    lines.append(f"  Pass rates: min={report.min_pass_rate:.0%} max={report.max_pass_rate:.0%} "
                 f"mean={report.mean_pass_rate:.0%} median={report.median_pass_rate:.0%}")
    lines.append(f"  Goals: {report.always_pass} always pass, "
                 f"{report.intermittent} intermittent, "
                 f"{report.always_fail} always fail")
    lines.append("")

    if report.always_fail > 0:
        lines.append("  Always failing:")
        for gs in report.goal_stability:
            if gs.stability == "always_fail":
                lines.append(f"    - {gs.goal} [{gs.dominant_failure}]")
        lines.append("")

    intermittent_goals = [gs for gs in report.goal_stability if gs.stability == "intermittent"]
    if intermittent_goals:
        lines.append("  Intermittent:")
        for gs in sorted(intermittent_goals, key=lambda g: g.pass_rate):
            lines.append(f"    - {gs.goal} ({gs.passes}/{gs.total_runs} pass) "
                         f"[{gs.dominant_failure}]")
        lines.append("")

    return "\n".join(lines)
