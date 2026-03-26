"""Planner orchestrator — retrieves candidates, invokes backend, validates output."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
        constraints=constraints or [],
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
