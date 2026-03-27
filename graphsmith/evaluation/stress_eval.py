"""Stress-frontier evaluation runner for progressively harder generalization probes."""
from __future__ import annotations

import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from graphsmith.evaluation.frontier_eval import (
    _evaluate_structure,
    _graph_skill_ids,
    _select_result_graph,
)
from graphsmith.planner.models import GlueGraph
from graphsmith.registry.base import RegistryBackend
from graphsmith.registry.local import LocalRegistry
from graphsmith.skills.closed_loop import run_closed_loop
from graphsmith.traces.models import NodeTrace, RunTrace
from graphsmith.traces.promotion import PromotionCandidate, find_promotion_candidates
from graphsmith.traces.store import TraceStore


class StressCase(BaseModel):
    id: str
    goal: str
    tier: int = 1
    tags: list[str] = Field(default_factory=list)
    expected_success: bool = True
    accepted_stop_reasons: list[str] = Field(default_factory=list)
    required_skill_ids: list[str] = Field(default_factory=list)
    forbidden_skill_ids: list[str] = Field(default_factory=list)
    required_graph_inputs: list[str] = Field(default_factory=list)
    required_output_names: list[str] = Field(default_factory=list)
    required_ops: list[str] = Field(default_factory=list)
    min_node_count: int = 0
    require_generated_skill: bool = False
    notes: str = ""


class StressCaseResult(BaseModel):
    id: str
    goal: str
    tier: int
    status: str = "fail"
    expected_success: bool = True
    observed_success: bool = False
    initial_status: str = ""
    detected_missing: bool = False
    generated_skill_id: str = ""
    replan_status: str = ""
    stopped_reason: str = ""
    structural_pass: bool = True
    structural_failures: list[str] = Field(default_factory=list)
    plan_skill_ids: list[str] = Field(default_factory=list)
    plan_input_names: list[str] = Field(default_factory=list)
    plan_output_names: list[str] = Field(default_factory=list)
    node_count: int = 0
    generated_skill_used_in_plan: bool = False
    reused_existing_skill_count: int = 0
    notes: str = ""


class StressReport(BaseModel):
    provider: str = ""
    model: str = ""
    mode: str = "isolated"
    timestamp: str = ""
    total: int = 0
    passed: int = 0
    pass_rate: float = 0.0
    observed_successes: int = 0
    generated_cases: int = 0
    generated_skill_ids: list[str] = Field(default_factory=list)
    unique_generated_skill_count: int = 0
    start_registry_size: int = 0
    final_registry_size: int = 0
    registry_growth: int = 0
    stop_reason_counts: dict[str, int] = Field(default_factory=dict)
    promotion_candidates: list[PromotionCandidate] = Field(default_factory=list)
    results: list[StressCaseResult] = Field(default_factory=list)


def load_stress_cases(goals_dir: str | Path) -> list[StressCase]:
    root = Path(goals_dir)
    return [
        StressCase.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(root.glob("*.json"))
    ]


def evaluate_stress_case(
    case: StressCase,
    registry: RegistryBackend,
    backend: object,
    *,
    trace_store: TraceStore | None = None,
) -> StressCaseResult:
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_closed_loop(
            case.goal,
            backend,
            registry,
            output_dir=tmpdir,
            auto_approve=True,
        )

    graph = _select_result_graph(result)
    structural_pass = True
    structural_failures: list[str] = []
    plan_skill_ids: list[str] = []
    plan_input_names: list[str] = []
    plan_output_names: list[str] = []
    node_count = 0

    if case.expected_success:
        structural_pass, structural_failures, plan_skill_ids, plan_input_names, plan_output_names, node_count = _evaluate_structure(case, graph, result)
        if graph is not None:
            missing_ops = [
                op for op in case.required_ops
                if op not in [node.op for node in graph.graph.nodes]
            ]
            for op in missing_ops:
                structural_failures.append(f"missing_required_op:{op}")
            structural_pass = not structural_failures
        passed = result.success and structural_pass
    else:
        passed = result.success == case.expected_success
        if (
            case.accepted_stop_reasons
            and result.stopped_reason not in case.accepted_stop_reasons
        ):
            passed = False
        if graph is not None:
            _, _, plan_skill_ids, plan_input_names, plan_output_names, node_count = _evaluate_structure(case, graph, result)

    if graph is not None and trace_store is not None:
        _save_synthetic_trace(trace_store, case, graph)

    generated_skill_id = result.generated_spec.skill_id if result.generated_spec else ""
    generated_skill_used_in_plan = bool(generated_skill_id and generated_skill_id in plan_skill_ids)
    reused_existing_skill_count = len(
        [sid for sid in plan_skill_ids if sid != generated_skill_id and "." in sid]
    )

    return StressCaseResult(
        id=case.id,
        goal=case.goal,
        tier=case.tier,
        status="pass" if passed else "fail",
        expected_success=case.expected_success,
        observed_success=bool(result.success),
        initial_status=result.initial_status,
        detected_missing=result.detected_missing,
        generated_skill_id=generated_skill_id,
        replan_status=result.replan_status,
        stopped_reason=result.stopped_reason,
        structural_pass=structural_pass,
        structural_failures=structural_failures,
        plan_skill_ids=plan_skill_ids,
        plan_input_names=plan_input_names,
        plan_output_names=plan_output_names,
        node_count=node_count,
        generated_skill_used_in_plan=generated_skill_used_in_plan,
        reused_existing_skill_count=reused_existing_skill_count,
        notes=case.notes,
    )


def run_stress_suite(
    cases: list[StressCase],
    registry: RegistryBackend,
    backend: object,
    *,
    provider_name: str = "",
    model_name: str = "",
    mode: str = "isolated",
) -> StressReport:
    with tempfile.TemporaryDirectory() as regdir, tempfile.TemporaryDirectory() as traces_dir:
        working_registry = LocalRegistry(regdir)
        for entry in registry.list_all():
            pkg = registry.fetch(entry.id, entry.version)
            working_registry.publish(pkg.root_path)
        start_registry_size = len(working_registry.list_all())
        trace_store = TraceStore(traces_dir)

        results: list[StressCaseResult] = []
        if mode == "cumulative":
            for case in cases:
                results.append(
                    evaluate_stress_case(case, working_registry, backend, trace_store=trace_store)
                )
        else:
            for case in cases:
                with tempfile.TemporaryDirectory() as case_regdir:
                    case_registry = LocalRegistry(case_regdir)
                    for entry in working_registry.list_all():
                        pkg = working_registry.fetch(entry.id, entry.version)
                        case_registry.publish(pkg.root_path)
                    results.append(
                        evaluate_stress_case(case, case_registry, backend, trace_store=trace_store)
                    )

        promotion_candidates = find_promotion_candidates(trace_store, min_frequency=2)
        final_registry_size = len(working_registry.list_all())

    total = len(results)
    passed = sum(1 for result in results if result.status == "pass")
    generated_skill_ids = [result.generated_skill_id for result in results if result.generated_skill_id]
    stop_reason_counts = Counter(result.stopped_reason for result in results if result.stopped_reason)
    observed_successes = sum(1 for result in results if result.observed_success)
    return StressReport(
        provider=provider_name,
        model=model_name,
        mode=mode,
        timestamp=datetime.now(timezone.utc).isoformat(),
        total=total,
        passed=passed,
        pass_rate=(passed / total) if total else 0.0,
        observed_successes=observed_successes,
        generated_cases=sum(1 for result in results if result.generated_skill_id),
        generated_skill_ids=generated_skill_ids,
        unique_generated_skill_count=len(set(generated_skill_ids)),
        start_registry_size=start_registry_size,
        final_registry_size=final_registry_size,
        registry_growth=final_registry_size - start_registry_size,
        stop_reason_counts=dict(sorted(stop_reason_counts.items())),
        promotion_candidates=promotion_candidates,
        results=results,
    )


def _save_synthetic_trace(
    store: TraceStore,
    case: StressCase,
    graph: GlueGraph,
) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    nodes: list[NodeTrace] = []
    for node in graph.graph.nodes:
        nodes.append(
            NodeTrace(
                node_id=node.id,
                op=node.op,
                status="ok",
                started_at=ts,
                ended_at=ts,
                inputs_summary={},
                outputs_summary={},
            )
        )
    trace = RunTrace(
        skill_id=f"stress.{case.id}",
        started_at=ts,
        ended_at=ts,
        status="ok",
        nodes=nodes,
        inputs_summary={field.name: field.type for field in graph.inputs},
        outputs_summary={field.name: field.type for field in graph.outputs},
    )
    return store.save(trace)
