"""Planner orchestrator — retrieves candidates, invokes backend, validates output."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import yaml

from graphsmith.exceptions import ExecutionError, PlannerError, ValidationError
from graphsmith.models import SkillPackage
from graphsmith.models.common import IOField
from graphsmith.models.package import ExamplesFile
from graphsmith.models.skill import SkillMetadata
from graphsmith.ops.llm_provider import LLMProvider
from graphsmith.planner.backend import PlannerBackend
from graphsmith.planner.candidates import retrieve_candidates_with_diagnostics
from graphsmith.planner.models import (
    GlueGraph,
    PlanRequest,
    PlanResult,
    UnresolvedHole,
)
from graphsmith.planner.policy import derive_goal_constraints
from graphsmith.registry.base import RegistryBackend
from graphsmith.validator import validate_skill_package


def compose_plan(
    goal: str,
    registry: RegistryBackend,
    backend: PlannerBackend,
    *,
    constraints: list[str] | None = None,
    desired_outputs: list[IOField] | None = None,
    max_candidates: int = 8,
) -> PlanResult:
    """End-to-end planning: retrieve → compose → validate.

    Returns a fully validated PlanResult. If the backend produces a
    graph that fails validation, the result is demoted to 'partial'
    or 'failure' and the validation error is attached as a hole.
    """
    # 1. Retrieve candidates
    retrieval, candidates = retrieve_candidates_with_diagnostics(
        goal, registry, max_candidates=max_candidates,
    )

    # 2. Build request
    request = PlanRequest(
        goal=goal,
        candidates=candidates,
        constraints=[*derive_goal_constraints(goal), *(constraints or [])],
        desired_outputs=desired_outputs or [],
    )

    # 3. Invoke backend
    result = backend.compose(request)
    result.candidates_considered = [
        f"{c.id}@{c.version}" for c in candidates
    ]
    result.retrieval = retrieval

    # 4. Validate the graph if present
    if result.graph is not None:
        result = _validate_glue_graph(result, registry=registry)

    return result


def _validate_glue_graph(
    result: PlanResult,
    *,
    registry: RegistryBackend | None = None,
) -> PlanResult:
    """Wrap the GlueGraph in a synthetic SkillPackage and validate it."""
    from graphsmith.planner.graph_repair import normalize_glue_graph_contracts

    glue = result.graph
    assert glue is not None
    glue, actions = normalize_glue_graph_contracts(glue, registry=registry)
    if actions:
        result = result.model_copy(
            update={
                "graph": glue,
                "repair_actions": [*result.repair_actions, *actions],
            }
        )
    else:
        result = result.model_copy(update={"graph": glue})

    pkg = glue_to_skill_package(glue)

    try:
        validate_skill_package(pkg)
    except ValidationError as exc:
        result = result.model_copy(
            update={
                "status": "partial" if result.status == "success" else result.status,
                "holes": [
                    *result.holes,
                    UnresolvedHole(
                        node_id="(validation)",
                        kind="validation_error",
                        description=str(exc),
                    ),
                ],
            }
        )
    return result


def glue_to_skill_package(glue: GlueGraph) -> SkillPackage:
    """Convert a GlueGraph into a synthetic SkillPackage for validation."""
    skill = SkillMetadata(
        id=f"_glue.{_slugify(glue.goal)}",
        name=f"Glue: {glue.goal[:60]}",
        version="0.0.0",
        description=glue.goal,
        inputs=glue.inputs,
        outputs=glue.outputs,
        effects=glue.effects,
    )
    return SkillPackage(
        root_path="(generated)",
        skill=skill,
        graph=glue.graph,
        examples=ExamplesFile(),
    )


def run_glue_graph(
    glue: GlueGraph,
    inputs: dict[str, Any],
    *,
    llm_provider: LLMProvider | None = None,
    registry: RegistryBackend | None = None,
) -> Any:
    """Validate and execute a GlueGraph. Returns an ExecutionResult.

    Raises PlannerError if the glue graph fails validation.
    Raises ExecutionError if execution fails.
    """
    from graphsmith.planner.graph_repair import (
        normalize_glue_graph_contracts,
        repair_glue_graph_from_runtime_error,
        repair_glue_graph_from_runtime_trace,
    )
    from graphsmith.runtime.executor import run_skill_package

    current_glue, runtime_repairs = normalize_glue_graph_contracts(
        glue, registry=registry,
    )
    used_trace_regeneration = False
    used_nested_region_regeneration = False
    for attempt in range(3):
        pkg = glue_to_skill_package(current_glue)
        try:
            validate_skill_package(pkg)
        except ValidationError as exc:
            raise PlannerError(f"Glue graph validation failed: {exc}") from exc

        try:
            result = run_skill_package(
                pkg, inputs, llm_provider=llm_provider, registry=registry,
            )
            result.repairs = list(runtime_repairs)
            return result
        except ExecutionError as exc:
            repaired_glue, actions = repair_glue_graph_from_runtime_error(
                current_glue, str(exc), registry=registry,
            )
            if actions:
                current_glue = repaired_glue
                runtime_repairs.extend(actions)
                continue

            if not used_nested_region_regeneration:
                repaired_glue, actions = repair_glue_graph_from_nested_runtime_trace(
                    current_glue,
                    trace=getattr(exc, "trace", None),
                    llm_provider=llm_provider,
                    registry=registry,
                )
                if actions:
                    used_nested_region_regeneration = True
                    current_glue = repaired_glue
                    runtime_repairs.extend(actions)
                    continue

            if not used_trace_regeneration:
                repaired_glue, actions = repair_glue_graph_from_runtime_trace(
                    current_glue,
                    str(exc),
                    trace=getattr(exc, "trace", None),
                    llm_provider=llm_provider,
                    registry=registry,
                )
                if actions:
                    used_trace_regeneration = True
                    current_glue = repaired_glue
                    runtime_repairs.extend(actions)
                    continue
            raise

    raise PlannerError("Glue graph execution repair loop exited unexpectedly")


def save_plan(glue: GlueGraph, path: str | Path) -> None:
    """Save a GlueGraph to a JSON file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(glue.model_dump(), indent=2) + "\n",
        encoding="utf-8",
    )


def load_plan(path: str | Path) -> GlueGraph:
    """Load a GlueGraph from a saved JSON file.

    Raises PlannerError on parse failure.
    """
    p = Path(path)
    if not p.exists():
        raise PlannerError(f"Plan file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return GlueGraph.model_validate(data)
    except (json.JSONDecodeError, Exception) as exc:
        raise PlannerError(f"Failed to load plan from {p}: {exc}") from exc


def _slugify(text: str) -> str:
    """Turn a goal string into a safe ID fragment."""
    slug = "".join(c if c.isalnum() else "_" for c in text.lower())
    return slug[:40].strip("_") or "plan"


def repair_glue_graph_from_nested_runtime_trace(
    glue: GlueGraph,
    *,
    trace: object | None,
    llm_provider: LLMProvider | None,
    registry: RegistryBackend | None,
) -> tuple[GlueGraph, list[str]]:
    """Repair a failing nested local subgraph and swap only that callsite."""
    if trace is None or llm_provider is None or registry is None:
        return glue, []
    trace_nodes = getattr(trace, "nodes", None)
    if not isinstance(trace_nodes, list):
        return glue, []

    node_map = {node.id: node for node in glue.graph.nodes}
    for node_trace in reversed(trace_nodes):
        child_trace = getattr(node_trace, "child_trace", None)
        if child_trace is None or getattr(child_trace, "status", "") != "error":
            continue
        graph_node = node_map.get(node_trace.node_id)
        if graph_node is None or graph_node.op != "skill.invoke":
            continue
        config = graph_node.config if isinstance(graph_node.config, dict) else {}
        skill_id = config.get("skill_id")
        version = config.get("version")
        if not isinstance(skill_id, str) or not isinstance(version, str):
            continue
        if not _is_nested_runtime_repairable_skill(skill_id, registry):
            continue
        try:
            pkg = registry.fetch(skill_id, version)
        except Exception:
            continue
        repaired_pkg, child_actions = _repair_nested_skill_package_from_trace(
            pkg,
            trace=child_trace,
            llm_provider=llm_provider,
            registry=registry,
        )
        if repaired_pkg is None:
            continue
        repaired_skill_id, repaired_version = _publish_repaired_skill_variant(
            repaired_pkg,
            registry=registry,
        )
        repaired_glue = _swap_skill_invoke_target(
            glue,
            node_trace.node_id,
            repaired_skill_id,
            repaired_version,
        )
        return repaired_glue, [
            *child_actions,
            (
                f"runtime:{node_trace.node_id}: swapped repaired nested skill "
                f"'{skill_id}@{version}' to '{repaired_skill_id}@{repaired_version}'"
            ),
        ]
    return glue, []


def _repair_nested_skill_package_from_trace(
    pkg: SkillPackage,
    *,
    trace: object,
    llm_provider: LLMProvider,
    registry: RegistryBackend,
) -> tuple[SkillPackage | None, list[str]]:
    """Recursively repair a failing local subgraph package from runtime trace evidence."""
    from graphsmith.planner.graph_repair import (
        normalize_glue_graph_contracts,
        repair_glue_graph_from_runtime_error,
        repair_glue_graph_from_runtime_trace,
    )

    glue = _skill_package_to_glue(pkg)
    trace_nodes = getattr(trace, "nodes", [])
    node_map = {node.id: node for node in glue.graph.nodes}

    for node_trace in reversed(trace_nodes):
        child_trace = getattr(node_trace, "child_trace", None)
        if child_trace is None or getattr(child_trace, "status", "") != "error":
            continue
        graph_node = node_map.get(node_trace.node_id)
        if graph_node is None or graph_node.op != "skill.invoke":
            continue
        config = graph_node.config if isinstance(graph_node.config, dict) else {}
        skill_id = config.get("skill_id")
        version = config.get("version")
        if not isinstance(skill_id, str) or not isinstance(version, str):
            continue
        if not _is_nested_runtime_repairable_skill(skill_id, registry):
            continue
        try:
            sub_pkg = registry.fetch(skill_id, version)
        except Exception:
            continue
        repaired_sub_pkg, child_actions = _repair_nested_skill_package_from_trace(
            sub_pkg,
            trace=child_trace,
            llm_provider=llm_provider,
            registry=registry,
        )
        if repaired_sub_pkg is None:
            continue
        repaired_skill_id, repaired_version = _publish_repaired_skill_variant(
            repaired_sub_pkg,
            registry=registry,
        )
        glue = _swap_skill_invoke_target(
            glue,
            node_trace.node_id,
            repaired_skill_id,
            repaired_version,
        )
        return _package_with_repaired_glue(pkg, glue), [
            *child_actions,
            (
                f"runtime:{node_trace.node_id}: swapped repaired nested skill "
                f"'{skill_id}@{version}' to '{repaired_skill_id}@{repaired_version}'"
            ),
        ]

    normalized_glue, actions = normalize_glue_graph_contracts(glue, registry=registry)
    repaired_glue, runtime_actions = repair_glue_graph_from_runtime_error(
        normalized_glue,
        getattr(trace, "error", "") or "",
        registry=registry,
    )
    actions.extend(runtime_actions)
    if not runtime_actions:
        repaired_glue, trace_actions = repair_glue_graph_from_runtime_trace(
            normalized_glue,
            getattr(trace, "error", "") or "",
            trace=trace,
            llm_provider=llm_provider,
            registry=registry,
        )
        actions.extend(trace_actions)
    if not actions:
        return None, []
    return _package_with_repaired_glue(pkg, repaired_glue), actions


def _skill_package_to_glue(pkg: SkillPackage) -> GlueGraph:
    return GlueGraph(
        goal=pkg.skill.description,
        inputs=pkg.skill.inputs,
        outputs=pkg.skill.outputs,
        effects=pkg.skill.effects,
        graph=pkg.graph,
    )


def _package_with_repaired_glue(pkg: SkillPackage, glue: GlueGraph) -> SkillPackage:
    return pkg.model_copy(
        update={
            "skill": pkg.skill.model_copy(
                update={
                    "description": glue.goal,
                    "inputs": glue.inputs,
                    "outputs": glue.outputs,
                    "effects": glue.effects,
                }
            ),
            "graph": glue.graph,
        }
    )


def _swap_skill_invoke_target(
    glue: GlueGraph,
    node_id: str,
    skill_id: str,
    version: str,
) -> GlueGraph:
    new_nodes = []
    for node in glue.graph.nodes:
        if node.id != node_id:
            new_nodes.append(node)
            continue
        config = dict(node.config)
        config["skill_id"] = skill_id
        config["version"] = version
        new_nodes.append(node.model_copy(update={"config": config}))
    return glue.model_copy(update={"graph": glue.graph.model_copy(update={"nodes": new_nodes})})


def _is_nested_runtime_repairable_skill(
    skill_id: str,
    registry: RegistryBackend,
) -> bool:
    if skill_id.startswith(("synth.", "repair.")):
        return True
    try:
        for entry in registry.list_all():
            if entry.id == skill_id:
                return entry.source_kind == "local"
    except Exception:
        return False
    return False


def _publish_repaired_skill_variant(
    pkg: SkillPackage,
    *,
    registry: RegistryBackend,
) -> tuple[str, str]:
    graph_dump = json.dumps(pkg.graph.model_dump(mode="json"), sort_keys=True)
    digest = hashlib.sha1(graph_dump.encode("utf-8")).hexdigest()[:8]
    base = pkg.skill.id.replace(".", "_")
    skill_id = f"repair.{base}_{digest}.v1"
    version = "1.0.0"

    try:
        registry.fetch(skill_id, version)
        return skill_id, version
    except Exception:
        pass

    repaired_pkg = pkg.model_copy(
        update={
            "skill": pkg.skill.model_copy(
                update={
                    "id": skill_id,
                    "version": version,
                    "name": f"Repaired {pkg.skill.name}",
                    "description": f"Repaired variant of {pkg.skill.id}",
                    "tags": sorted(set([*pkg.skill.tags, "repaired", "subgraph"])),
                    "authors": sorted(set([*pkg.skill.authors, "graphsmith"])),
                }
            )
        }
    )
    validate_skill_package(repaired_pkg)

    root = Path(tempfile.mkdtemp()) / skill_id
    root.mkdir(parents=True, exist_ok=True)
    _write_skill_package_files(repaired_pkg, root)
    registry.publish(root)
    return skill_id, version


def _write_skill_package_files(pkg: SkillPackage, root: Path) -> None:
    (root / "skill.yaml").write_text(
        yaml.safe_dump(pkg.skill.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    (root / "graph.yaml").write_text(
        yaml.safe_dump(pkg.graph.model_dump(mode="json", by_alias=True), sort_keys=False),
        encoding="utf-8",
    )
    (root / "examples.yaml").write_text(
        yaml.safe_dump(pkg.examples.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
