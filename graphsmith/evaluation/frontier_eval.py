"""Frontier evaluation runner for closed-loop generalization probes."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from graphsmith.models.graph import GraphBody, GraphNode
from graphsmith.planner.models import GlueGraph
from graphsmith.registry.base import RegistryBackend
from graphsmith.registry.local import LocalRegistry
from graphsmith.skills.closed_loop import run_closed_loop


class FrontierCase(BaseModel):
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
    min_node_count: int = 0
    require_generated_skill: bool = False
    notes: str = ""


class FrontierCaseResult(BaseModel):
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
    notes: str = ""


class FrontierReport(BaseModel):
    provider: str = ""
    model: str = ""
    timestamp: str = ""
    total: int = 0
    passed: int = 0
    pass_rate: float = 0.0
    results: list[FrontierCaseResult] = Field(default_factory=list)


def load_frontier_cases(goals_dir: str | Path) -> list[FrontierCase]:
    root = Path(goals_dir)
    return [
        FrontierCase.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(root.glob("*.json"))
    ]


def _select_result_graph(result) -> GlueGraph | None:
    if result.replan_plan is not None:
        return result.replan_plan
    if result.initial_plan is not None:
        return result.initial_plan
    return None


def _iter_graph_nodes(body: GraphBody) -> list[GraphNode]:
    nodes: list[GraphNode] = []
    for node in body.nodes:
        nodes.append(node)
        if node.op != "parallel.map":
            continue
        config = node.config if isinstance(node.config, dict) else {}
        if config.get("mode") != "inline_graph":
            continue
        raw_body = config.get("body")
        if not isinstance(raw_body, dict):
            continue
        raw_graph = raw_body.get("graph")
        if not isinstance(raw_graph, dict):
            continue
        try:
            nested_body = GraphBody.model_validate(raw_graph)
        except Exception:
            continue
        nodes.extend(_iter_graph_nodes(nested_body))
    return nodes


def _graph_skill_ids(graph: GlueGraph) -> list[str]:
    skill_ids: list[str] = []
    for node in _iter_graph_nodes(graph.graph):
        if node.op == "skill.invoke" and isinstance(node.config, dict):
            skill_id = node.config.get("skill_id")
            if isinstance(skill_id, str):
                skill_ids.append(skill_id)
        else:
            skill_ids.append(node.op)
    return skill_ids


def _evaluate_structure(case: FrontierCase, graph: GlueGraph | None, result) -> tuple[bool, list[str], list[str], list[str], list[str], int]:
    if graph is None:
        return False, ["no_graph"], [], [], [], 0

    failures: list[str] = []
    skill_ids = _graph_skill_ids(graph)
    input_names = [field.name for field in graph.inputs]
    output_names = [field.name for field in graph.outputs]
    node_count = len(_iter_graph_nodes(graph.graph))

    for skill_id in case.required_skill_ids:
        if skill_id not in skill_ids:
            failures.append(f"missing_required_skill:{skill_id}")
    for skill_id in case.forbidden_skill_ids:
        if skill_id in skill_ids:
            failures.append(f"forbidden_skill_present:{skill_id}")
    for input_name in case.required_graph_inputs:
        if input_name not in input_names:
            failures.append(f"missing_required_input:{input_name}")
    for output_name in case.required_output_names:
        if output_name not in output_names:
            failures.append(f"missing_required_output:{output_name}")
    if case.min_node_count and node_count < case.min_node_count:
        failures.append(f"node_count_below_min:{node_count}<{case.min_node_count}")
    if case.require_generated_skill and not result.generated_spec:
        failures.append("generated_skill_not_used")

    return not failures, failures, skill_ids, input_names, output_names, node_count


def evaluate_frontier_case(
    case: FrontierCase,
    registry: RegistryBackend,
    backend: object,
) -> FrontierCaseResult:
    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as regdir:
        case_registry = LocalRegistry(regdir)
        for entry in registry.list_all():
            pkg = registry.fetch(entry.id, entry.version)
            case_registry.publish(pkg.root_path)
        result = run_closed_loop(
            case.goal,
            backend,
            case_registry,
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

    return FrontierCaseResult(
        id=case.id,
        goal=case.goal,
        tier=case.tier,
        status="pass" if passed else "fail",
        expected_success=case.expected_success,
        observed_success=bool(result.success),
        initial_status=result.initial_status,
        detected_missing=result.detected_missing,
        generated_skill_id=result.generated_spec.skill_id if result.generated_spec else "",
        replan_status=result.replan_status,
        stopped_reason=result.stopped_reason,
        structural_pass=structural_pass,
        structural_failures=structural_failures,
        plan_skill_ids=plan_skill_ids,
        plan_input_names=plan_input_names,
        plan_output_names=plan_output_names,
        node_count=node_count,
        notes=case.notes,
    )


def run_frontier_suite(
    cases: list[FrontierCase],
    registry: RegistryBackend,
    backend: object,
    *,
    provider_name: str = "",
    model_name: str = "",
) -> FrontierReport:
    results = [evaluate_frontier_case(case, registry, backend) for case in cases]
    total = len(results)
    passed = sum(1 for result in results if result.status == "pass")
    return FrontierReport(
        provider=provider_name,
        model=model_name,
        timestamp=datetime.now(timezone.utc).isoformat(),
        total=total,
        passed=passed,
        pass_rate=(passed / total) if total else 0.0,
        results=results,
    )
