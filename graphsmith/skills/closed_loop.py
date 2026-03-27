"""Closed-loop planning: detect missing skill → generate → validate → replan.

Bounded prototype that handles exactly one missing deterministic single-step skill.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
import yaml

from graphsmith.planner.decomposition import decompose_deterministic
from graphsmith.planner.compiler import compile_ir
from graphsmith.planner.ir import IRBlock, IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.ir_backend import CandidateResult
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.planner.models import GlueGraph, PlanRequest, PlanResult
from graphsmith.planner.policy import (
    derive_goal_constraints,
    filter_candidates_by_goal_policy,
    requires_published_only,
    requires_trusted_published_only,
)
from graphsmith.registry.base import RegistryBackend
from graphsmith.skills.autogen import (
    AutogenError,
    SkillSpec,
    _spec_from_template,
    extract_spec,
    format_result,
    generate_skill_files,
    match_template_keys,
    register_generated_op,
    unregister_generated_op,
    validate_and_test,
)
from graphsmith.registry.index import IndexEntry

_TRANSFORM_SKILL_IDS: dict[str, str] = {
    "normalize": "text.normalize.v1",
    "summarize": "text.summarize.v1",
    "extract_keywords": "text.extract_keywords.v1",
    "title_case": "text.title_case.v1",
    "classify_sentiment": "text.classify_sentiment.v1",
    "word_count": "text.word_count.v1",
    "sort_lines": "text.sort_lines.v1",
    "remove_duplicates": "text.remove_duplicates.v1",
    "join_lines": "text.join_lines.v1",
    "reshape_json": "json.reshape.v1",
    "extract_field": "json.extract_field.v1",
    "pretty_print": "json.pretty_print.v1",
}


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
    registry: RegistryBackend, skill_id: str,
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
    registry: RegistryBackend,
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
    synthesized_skill_id: str = ""
    synthesis_dir: str = ""
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


def _can_use_generated_in_composition(spec: SkillSpec) -> bool:
    """Allow bounded composition fallback for generated skills with real ports."""
    return True


def _goal_has_loop_semantics(goal: str) -> bool:
    goal_lower = goal.lower()
    return "for each " in goal_lower or goal_lower.startswith("for each") or " each " in goal_lower


def _goal_needs_multiple_generated_skills(goal: str) -> bool:
    keys = [
        key for key in match_template_keys(goal)
        if key not in {"pretty", "join"}
    ]
    return len(keys) > 1


def _goal_has_filesystem_boundary(goal: str) -> bool:
    goal_lower = goal.lower()
    return any(token in goal_lower for token in (" file ", " disk", "filesystem", " path", "from disk", "read a "))


def _goal_supports_loop_generated_fallback(goal: str) -> bool:
    if not _goal_has_loop_semantics(goal):
        return False
    keys = match_template_keys(goal)
    if keys != ["contains"]:
        return False
    transforms = decompose_deterministic(goal).content_transforms
    return transforms in (["normalize", "summarize"], ["extract_field", "pretty_print"])


def _goal_supports_two_generated_linear_fallback(goal: str) -> bool:
    if _goal_has_loop_semantics(goal):
        return False
    if _goal_matches_sentiment_branch_prefix(goal):
        return False
    if _goal_has_filesystem_boundary(goal):
        return False
    keys = set(match_template_keys(goal))
    return keys == {"uppercase", "starts_with"}


def _goal_supports_structured_numeric_fallback(goal: str) -> bool:
    if _goal_has_loop_semantics(goal):
        return False
    if _goal_matches_sentiment_branch_prefix(goal):
        return False
    if _goal_has_filesystem_boundary(goal):
        return False

    keys = set(match_template_keys(goal))
    allowed = {"median", "max", "min", "divide", "contains", "pretty"}
    if not keys or not keys.issubset(allowed):
        return False
    numeric_keys = keys & {"median", "max", "min"}
    if not numeric_keys:
        return False
    if "divide" in keys and len(numeric_keys) != 1:
        return False

    decomp = decompose_deterministic(goal)
    return "pretty_print" in decomp.content_transforms


def _goal_matches_read_normalize(goal: str) -> bool:
    goal_lower = goal.lower()
    return (
        "read" in goal_lower
        and "file" in goal_lower
        and "normalize" in goal_lower
        and "write" not in goal_lower
    )


def _goal_matches_read_normalize_write(goal: str) -> bool:
    goal_lower = goal.lower()
    return (
        "read" in goal_lower
        and "file" in goal_lower
        and "normalize" in goal_lower
        and "write" in goal_lower
    )


def _goal_matches_run_pytest(goal: str) -> bool:
    goal_lower = goal.lower()
    return (
        "pytest" in goal_lower
        and "run" in goal_lower
        and "summarize" not in goal_lower
        and "prefix" not in goal_lower
        and "read" not in goal_lower
        and "write" not in goal_lower
    )


def _goal_matches_run_command_starts_with(goal: str) -> bool:
    goal_lower = goal.lower()
    return "command" in goal_lower and "starts with" in goal_lower


def _goal_matches_read_replace_write(goal: str) -> bool:
    goal_lower = goal.lower()
    return (
        "read" in goal_lower
        and "file" in goal_lower
        and "replace" in goal_lower
        and "write" in goal_lower
    )


def _goal_matches_pytest_prefix_branch(goal: str) -> bool:
    goal_lower = goal.lower()
    return (
        "pytest" in goal_lower
        and "if tests fail" in goal_lower
        and "otherwise" in goal_lower
        and "prefix each output line" in goal_lower
    )


def _goal_matches_loop_read_contains(goal: str) -> bool:
    goal_lower = goal.lower()
    return (
        _goal_has_loop_semantics(goal)
        and "file" in goal_lower
        and "contain" in goal_lower
        and "phrase" in goal_lower
    )


def _goal_supports_environment_fallback(goal: str) -> bool:
    return any((
        _goal_matches_read_normalize(goal),
        _goal_matches_read_normalize_write(goal),
        _goal_matches_run_pytest(goal),
        _goal_matches_run_command_starts_with(goal),
        _goal_matches_read_replace_write(goal),
        _goal_matches_pytest_prefix_branch(goal),
        _goal_matches_loop_read_contains(goal),
    ))


def _goal_matches_sentiment_branch_body_prefix(goal: str) -> bool:
    goal_lower = goal.lower()
    return (
        "sentiment" in goal_lower
        and "positive" in goal_lower
        and ("otherwise" in goal_lower or "else" in goal_lower)
        and ("summarize" in goal_lower or "summary" in goal_lower)
        and "keyword" in goal_lower
        and ("prefix each resulting line" in goal_lower or "prefix each line" in goal_lower)
    )


def _goal_matches_sentiment_branch_prefix(goal: str) -> bool:
    goal_lower = goal.lower()
    return (
        "sentiment" in goal_lower
        and "positive" in goal_lower
        and "otherwise" in goal_lower
        and ("prefix each line" in goal_lower or "prefix the lines" in goal_lower)
    )


def _expected_existing_skill_ids(goal: str) -> list[str]:
    """Expected existing skills from deterministic decomposition."""
    if _goal_has_loop_semantics(goal):
        return []
    decomp = decompose_deterministic(goal)
    skill_ids: list[str] = []
    for transform in decomp.content_transforms:
        skill_id = _TRANSFORM_SKILL_IDS.get(transform)
        if skill_id is not None:
            skill_ids.append(skill_id)
    if decomp.presentation == "list" and "text.join_lines.v1" not in skill_ids:
        skill_ids.append("text.join_lines.v1")
    return skill_ids


def _autogen_conflicts_with_existing_pipeline(goal: str, spec: SkillSpec) -> bool:
    expected = _expected_existing_skill_ids(goal)
    return spec.skill_id == "text.join.v1" and "text.join_lines.v1" in expected


def _semantic_fidelity_block_reason(goal: str) -> str:
    """Return a bounded reason when the goal exceeds current closed-loop fidelity."""
    if _goal_matches_sentiment_branch_prefix(goal):
        return ""
    if _goal_matches_sentiment_branch_body_prefix(goal):
        return ""
    if _goal_matches_loop_read_contains(goal):
        return ""
    if _goal_supports_structured_numeric_fallback(goal):
        return ""
    if requires_trusted_published_only(goal):
        return "semantic_fidelity_blocked"
    if requires_published_only(goal) and match_template_keys(goal):
        return "semantic_fidelity_blocked"
    if _goal_needs_multiple_generated_skills(goal) and not _goal_supports_two_generated_linear_fallback(goal):
        return "semantic_fidelity_blocked"
    if _goal_has_loop_semantics(goal) and match_template_keys(goal) and not _goal_supports_loop_generated_fallback(goal):
        return "semantic_fidelity_blocked"
    if _goal_has_filesystem_boundary(goal) and not _goal_supports_environment_fallback(goal):
        return "semantic_fidelity_blocked"
    return ""


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
            nodes=[GraphNode(id="generated", op="skill.invoke", config={"skill_id": spec.skill_id, "version": "1.0.0"})],
            edges=[
                GraphEdge(from_=f"input.{inp['name']}", to=f"generated.{inp['name']}")
                for inp in spec.inputs
            ],
            outputs={out["name"]: f"generated.{out['name']}" for out in spec.outputs},
        ),
    )


def _find_registry_entry(
    registry: RegistryBackend, skill_id: str,
) -> IndexEntry | None:
    return _find_registry_entry_by_id(registry, skill_id)


def _build_linear_pipeline_plan(
    goal: str,
    registry: RegistryBackend,
    skill_ids: list[str],
) -> GlueGraph | None:
    """Build a simple linear pipeline from exact skill ids.

    Bounded to chains where each downstream skill has exactly one required input.
    """
    from graphsmith.models.common import IOField
    from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode

    if not skill_ids:
        return None

    packages = []
    for skill_id in skill_ids:
        entry = _find_registry_entry(registry, skill_id)
        if entry is None:
            return None
        try:
            packages.append(registry.fetch(entry.id, entry.version))
        except Exception:
            return None

    first_pkg = packages[0]
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    input_fields: dict[str, IOField] = {}

    def ensure_graph_input(field) -> None:
        if field.name not in input_fields:
            input_fields[field.name] = IOField(
                name=field.name,
                type=field.type,
                required=field.required,
            )

    def choose_upstream_input(required_inputs, prev_output_name: str):
        by_name = {field.name: field for field in required_inputs}
        for preferred in ("text", "lines", "raw_json", "values"):
            if preferred in by_name:
                return by_name[preferred]
        if prev_output_name in by_name:
            return by_name[prev_output_name]
        if len(required_inputs) == 1:
            return required_inputs[0]
        return None

    for idx, pkg in enumerate(packages):
        node_id = f"step_{idx + 1}"
        nodes.append(
            GraphNode(
                id=node_id,
                op="skill.invoke",
                config={"skill_id": pkg.skill.id, "version": pkg.skill.version},
            )
        )
        required_inputs = [field for field in pkg.skill.inputs if field.required]
        if idx == 0:
            for field in required_inputs:
                ensure_graph_input(field)
                edges.append(GraphEdge(from_=f"input.{field.name}", to=f"{node_id}.{field.name}"))
            continue
        prev_pkg = packages[idx - 1]
        if not prev_pkg.skill.outputs:
            return None
        upstream_port = prev_pkg.skill.outputs[0].name
        upstream_input = choose_upstream_input(required_inputs, upstream_port)
        if upstream_input is None:
            return None
        edges.append(
            GraphEdge(from_=f"step_{idx}.{upstream_port}", to=f"{node_id}.{upstream_input.name}")
        )
        for field in required_inputs:
            if field.name == upstream_input.name:
                continue
            ensure_graph_input(field)
            edges.append(GraphEdge(from_=f"input.{field.name}", to=f"{node_id}.{field.name}"))

    last_pkg = packages[-1]
    graph_outputs = {
        field.name: f"step_{len(packages)}.{field.name}"
        for field in last_pkg.skill.outputs
    }
    outputs = [IOField(name=field.name, type=field.type) for field in last_pkg.skill.outputs]

    return GlueGraph(
        goal=goal,
        inputs=list(input_fields.values()),
        outputs=outputs,
        effects=sorted({effect for pkg in packages for effect in pkg.skill.effects}),
        graph=GraphBody(version=1, nodes=nodes, edges=edges, outputs=graph_outputs),
    )


def _build_multi_stage_fallback_plan(
    goal: str,
    registry: RegistryBackend,
    generated_spec: SkillSpec,
) -> GlueGraph | None:
    """Build a bounded linear fallback for simple mixed compositions.

    This covers cases like:
    - normalize -> uppercase
    - summarize -> uppercase
    - normalize -> char_count
    - extract_keywords -> uppercase
    """
    if not _can_use_generated_in_composition(generated_spec):
        return None
    if _goal_has_loop_semantics(goal):
        return None
    if _goal_needs_multiple_generated_skills(goal):
        return None

    # Keep this bounded to a single generated text skill composed with existing
    # text/JSON transforms. Math-heavy mixed chains still need stronger ordering.
    if generated_spec.category != "text":
        return None

    decomp = decompose_deterministic(goal)
    skill_ids: list[str] = []

    for transform in decomp.content_transforms:
        skill_id = _TRANSFORM_SKILL_IDS.get(transform)
        if skill_id is None:
            return None
        skill_ids.append(skill_id)

    if decomp.presentation == "list":
        skill_ids.append("text.join_lines.v1")

    if generated_spec.skill_id not in skill_ids:
        skill_ids.append(generated_spec.skill_id)

    if len(skill_ids) < 2:
        return None

    return _build_linear_pipeline_plan(goal, registry, skill_ids)


def _build_existing_skill_fallback_plan(
    goal: str,
    registry: RegistryBackend,
) -> GlueGraph | None:
    """Build a bounded fallback graph using only existing published skills."""
    if _goal_has_loop_semantics(goal):
        return None

    decomp = decompose_deterministic(goal)
    if not decomp.content_transforms:
        return None

    skill_ids: list[str] = []
    for transform in decomp.content_transforms:
        skill_id = _TRANSFORM_SKILL_IDS.get(transform)
        if skill_id is None:
            return None
        skill_ids.append(skill_id)

    if decomp.presentation == "list" and "text.join_lines.v1" not in skill_ids:
        skill_ids.append("text.join_lines.v1")

    if len(skill_ids) < 2:
        return None

    return _build_linear_pipeline_plan(goal, registry, skill_ids)


def _build_loop_fallback_plan(
    goal: str,
    registry: RegistryBackend,
    generated_spec: SkillSpec,
) -> GlueGraph | None:
    """Build a bounded loop-region fallback using the existing IR loop lowering."""
    if generated_spec.skill_id != "text.contains.v1":
        return None
    if not _goal_supports_loop_generated_fallback(goal):
        return None

    decomp = decompose_deterministic(goal)
    transforms = decomp.content_transforms
    steps: list[IRStep] = []
    previous_step: str | None = None
    previous_port: str | None = None

    item_collection_name = "texts"
    item_collection_type = "array<string>"
    loop_input_name = "text"
    if transforms == ["extract_field", "pretty_print"]:
        item_collection_name = "json_objects"
        item_collection_type = "array<string>"
        loop_input_name = "raw_json"

    for transform in transforms:
        skill_id = _TRANSFORM_SKILL_IDS.get(transform)
        if skill_id is None:
            return None
        if previous_step is None:
            sources = {loop_input_name: IRSource(step="input", port=loop_input_name)}
        else:
            next_input = "text"
            if transform == "pretty_print":
                next_input = "raw_json"
            sources = {next_input: IRSource(step=previous_step, port=previous_port)}
        step_name = transform
        steps.append(IRStep(name=step_name, skill_id=skill_id, sources=sources))
        previous_step = step_name
        previous_port = {
            "normalize": "normalized",
            "summarize": "summary",
            "extract_field": "value",
            "pretty_print": "formatted",
        }[transform]

    if previous_step is None or previous_port is None:
        return None

    steps.append(
        IRStep(
            name="contains",
            skill_id=generated_spec.skill_id,
            sources={
                "text": IRSource(step=previous_step, port=previous_port),
                "substring": IRSource(step="input", port="substring"),
            },
        )
    )

    ir = PlanningIR(
        goal=goal,
        inputs=[
            IRInput(name=item_collection_name, type=item_collection_type),
            IRInput(name="substring", type="string"),
        ],
        steps=[],
        blocks=[
            IRBlock(
                name="process_each",
                kind="loop",
                collection=IRSource(step="input", port=item_collection_name),
                inputs={
                    loop_input_name: IRSource(binding="item"),
                    "substring": IRSource(step="input", port="substring"),
                },
                steps=steps,
                final_outputs={"result": IROutputRef(step="contains", port="result")},
                max_items=50,
            )
        ],
        final_outputs={"result": IROutputRef(step="process_each", port="result")},
        effects=["pure", "llm_inference"],
    )
    return compile_ir(ir)


def _build_two_generated_linear_fallback_plan(
    goal: str,
    registry: RegistryBackend,
    generated_specs: list[SkillSpec],
) -> GlueGraph | None:
    if not _goal_supports_two_generated_linear_fallback(goal):
        return None
    spec_by_key = {spec.template_key: spec for spec in generated_specs}
    if {"uppercase", "starts_with"} - set(spec_by_key):
        return None

    decomp = decompose_deterministic(goal)
    skill_ids: list[str] = []
    for transform in decomp.content_transforms:
        skill_id = _TRANSFORM_SKILL_IDS.get(transform)
        if skill_id is None:
            return None
        skill_ids.append(skill_id)
    skill_ids.append(spec_by_key["uppercase"].skill_id)
    skill_ids.append(spec_by_key["starts_with"].skill_id)
    return _build_linear_pipeline_plan(goal, registry, skill_ids)


def _build_structured_numeric_fallback_plan(
    goal: str,
    registry: RegistryBackend,
    generated_specs: list[SkillSpec],
) -> GlueGraph | None:
    """Build a bounded structured numeric plan.

    Supported shape:
    - one or two numeric reducers over `values`
    - optional binary divide over a single reducer and a public `divisor`
    - pack scalar outputs into JSON
    - pretty print JSON
    - optional contains over the formatted JSON
    """
    from graphsmith.models.common import IOField
    from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode

    if not _goal_supports_structured_numeric_fallback(goal):
        return None

    spec_by_key = {spec.template_key: spec for spec in generated_specs}
    goal_keys = match_template_keys(goal)
    numeric_keys = [key for key in goal_keys if key in {"median", "max", "min"}]
    if not numeric_keys:
        return None

    available_ids = {entry.id for entry in registry.list_all()} if hasattr(registry, "list_all") else set()
    required_skill_ids = ["json.pretty_print.v1"]
    if "contains" in goal_keys:
        required_skill_ids.append("text.contains.v1")
    for skill_id in required_skill_ids:
        if skill_id not in available_ids:
            return None

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    inputs: list[IOField] = [IOField(name="values", type="string")]

    scalar_ports: dict[str, str] = {}
    for key in numeric_keys:
        spec = spec_by_key.get(key)
        if spec is None:
            return None
        node_id = key
        nodes.append(
            GraphNode(
                id=node_id,
                op="skill.invoke",
                config={"skill_id": spec.skill_id, "version": "1.0.0"},
            )
        )
        edges.append(GraphEdge(from_="input.values", to=f"{node_id}.values"))
        scalar_ports[key] = f"{node_id}.result"

    packed_fields: dict[str, str] = {}
    if "divide" in goal_keys:
        divide_spec = spec_by_key.get("divide")
        if divide_spec is None or len(numeric_keys) != 1:
            return None
        nodes.append(
            GraphNode(id="divide", op="skill.invoke", config={"skill_id": divide_spec.skill_id, "version": "1.0.0"})
        )
        edges.append(GraphEdge(from_=scalar_ports[numeric_keys[0]], to="divide.a"))
        edges.append(GraphEdge(from_="input.divisor", to="divide.b"))
        inputs.append(IOField(name="divisor", type="string"))
        packed_fields["result"] = "divide.result"
    else:
        label_map = {"median": "median", "max": "maximum", "min": "minimum"}
        for key in numeric_keys:
            packed_fields[label_map[key]] = scalar_ports[key]

    nodes.append(GraphNode(id="pack", op="json.pack"))
    for field_name, source in packed_fields.items():
        edges.append(GraphEdge(from_=source, to=f"pack.{field_name}"))

    nodes.append(
        GraphNode(id="pretty", op="skill.invoke", config={"skill_id": "json.pretty_print.v1", "version": "1.0.0"})
    )
    edges.append(GraphEdge(from_="pack.raw_json", to="pretty.raw_json"))

    outputs = [IOField(name="formatted", type="string")]
    graph_outputs = {"formatted": "pretty.formatted"}

    if "contains" in goal_keys:
        contains_spec = spec_by_key.get("contains")
        if contains_spec is None:
            return None
        nodes.append(
            GraphNode(id="contains", op="skill.invoke", config={"skill_id": contains_spec.skill_id, "version": "1.0.0"})
        )
        edges.append(GraphEdge(from_="pretty.formatted", to="contains.text"))
        edges.append(GraphEdge(from_="input.substring", to="contains.substring"))
        inputs.append(IOField(name="substring", type="string"))
        outputs.append(IOField(name="result", type="string"))
        graph_outputs["result"] = "contains.result"

    return GlueGraph(
        goal=goal,
        inputs=inputs,
        outputs=outputs,
        effects=["pure"],
        graph=GraphBody(
            version=1,
            nodes=nodes,
            edges=edges,
            outputs=graph_outputs,
        ),
    )


def _build_read_normalize_plan(goal: str, registry: RegistryBackend) -> GlueGraph | None:
    from graphsmith.models.common import IOField
    from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode

    required = {"fs.read_text.v1", "text.normalize.v1"}
    available = {entry.id for entry in registry.list_all()} if hasattr(registry, "list_all") else set()
    if not required.issubset(available):
        return None
    return GlueGraph(
        goal=goal,
        inputs=[IOField(name="path", type="string")],
        outputs=[IOField(name="normalized", type="string")],
        effects=["filesystem_read", "pure"],
        graph=GraphBody(
            version=1,
            nodes=[
                GraphNode(id="read", op="skill.invoke", config={"skill_id": "fs.read_text.v1", "version": "1.0.0"}),
                GraphNode(id="normalize", op="skill.invoke", config={"skill_id": "text.normalize.v1", "version": "1.0.0"}),
            ],
            edges=[
                GraphEdge(from_="input.path", to="read.path"),
                GraphEdge(from_="read.text", to="normalize.text"),
            ],
            outputs={"normalized": "normalize.normalized"},
        ),
    )


def _build_read_normalize_write_plan(goal: str, registry: RegistryBackend) -> GlueGraph | None:
    from graphsmith.models.common import IOField
    from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode

    required = {"fs.read_text.v1", "text.normalize.v1", "fs.write_text.v1"}
    available = {entry.id for entry in registry.list_all()} if hasattr(registry, "list_all") else set()
    if not required.issubset(available):
        return None
    return GlueGraph(
        goal=goal,
        inputs=[
            IOField(name="input_path", type="string"),
            IOField(name="output_path", type="string"),
        ],
        outputs=[IOField(name="path", type="string")],
        effects=["filesystem_read", "filesystem_write", "pure"],
        graph=GraphBody(
            version=1,
            nodes=[
                GraphNode(id="read", op="skill.invoke", config={"skill_id": "fs.read_text.v1", "version": "1.0.0"}),
                GraphNode(id="normalize", op="skill.invoke", config={"skill_id": "text.normalize.v1", "version": "1.0.0"}),
                GraphNode(id="write", op="skill.invoke", config={"skill_id": "fs.write_text.v1", "version": "1.0.0"}),
            ],
            edges=[
                GraphEdge(from_="input.input_path", to="read.path"),
                GraphEdge(from_="read.text", to="normalize.text"),
                GraphEdge(from_="input.output_path", to="write.path"),
                GraphEdge(from_="normalize.normalized", to="write.text"),
            ],
            outputs={"path": "write.path"},
        ),
    )


def _build_run_pytest_plan(goal: str, registry: RegistryBackend) -> GlueGraph | None:
    from graphsmith.models.common import IOField
    from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode

    available = {entry.id for entry in registry.list_all()} if hasattr(registry, "list_all") else set()
    if "dev.run_pytest.v1" not in available:
        return None
    return GlueGraph(
        goal=goal,
        inputs=[IOField(name="cwd", type="string")],
        outputs=[IOField(name="stdout", type="string")],
        effects=["shell_exec"],
        graph=GraphBody(
            version=1,
            nodes=[
                GraphNode(id="pytest", op="skill.invoke", config={"skill_id": "dev.run_pytest.v1", "version": "1.0.0"}),
            ],
            edges=[GraphEdge(from_="input.cwd", to="pytest.cwd")],
            outputs={"stdout": "pytest.stdout"},
        ),
    )


def _build_run_pytest_prefix_branch_plan(goal: str, registry: RegistryBackend) -> GlueGraph | None:
    from graphsmith.models.common import IOField
    from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode

    available = {entry.id for entry in registry.list_all()} if hasattr(registry, "list_all") else set()
    if not {"dev.run_pytest.v1", "text.prefix_lines.v1"}.issubset(available):
        return None
    return GlueGraph(
        goal=goal,
        inputs=[IOField(name="cwd", type="string")],
        outputs=[IOField(name="prefixed", type="string")],
        effects=["shell_exec", "pure"],
        graph=GraphBody(
            version=1,
            nodes=[
                GraphNode(id="pytest", op="skill.invoke", config={"skill_id": "dev.run_pytest.v1", "version": "1.0.0"}),
                GraphNode(id="zero", op="template.render", config={"template": "0"}),
                GraphNode(id="is_success", op="text.equals"),
                GraphNode(id="pass_label", op="template.render", config={"template": "PASS"}),
                GraphNode(id="fail_label", op="template.render", config={"template": "FAIL"}),
                GraphNode(
                    id="prefix_pass",
                    op="skill.invoke",
                    config={"skill_id": "text.prefix_lines.v1", "version": "1.0.0"},
                    when="is_success.result",
                ),
                GraphNode(
                    id="prefix_fail",
                    op="skill.invoke",
                    config={"skill_id": "text.prefix_lines.v1", "version": "1.0.0"},
                    when="!is_success.result",
                ),
                GraphNode(id="merge_prefixed", op="fallback.try"),
            ],
            edges=[
                GraphEdge(from_="input.cwd", to="pytest.cwd"),
                GraphEdge(from_="pytest.exit_code", to="is_success.text"),
                GraphEdge(from_="zero.rendered", to="is_success.other"),
                GraphEdge(from_="pytest.stdout", to="prefix_pass.text"),
                GraphEdge(from_="pass_label.rendered", to="prefix_pass.prefix"),
                GraphEdge(from_="pytest.stdout", to="prefix_fail.text"),
                GraphEdge(from_="fail_label.rendered", to="prefix_fail.prefix"),
                GraphEdge(from_="prefix_pass.prefixed", to="merge_prefixed.primary"),
                GraphEdge(from_="prefix_fail.prefixed", to="merge_prefixed.fallback"),
            ],
            outputs={"prefixed": "merge_prefixed.result"},
        ),
    )


def _build_run_command_starts_with_plan(
    goal: str,
    registry: RegistryBackend,
    generated_spec: SkillSpec,
) -> GlueGraph | None:
    from graphsmith.models.common import IOField
    from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode

    available = {entry.id for entry in registry.list_all()} if hasattr(registry, "list_all") else set()
    if not {"dev.run_command.v1", generated_spec.skill_id}.issubset(available) or generated_spec.skill_id != "text.starts_with.v1":
        return None
    return GlueGraph(
        goal=goal,
        inputs=[
            IOField(name="argv", type="array<string>"),
            IOField(name="cwd", type="string"),
            IOField(name="prefix", type="string"),
        ],
        outputs=[IOField(name="result", type="string")],
        effects=["shell_exec", "pure"],
        graph=GraphBody(
            version=1,
            nodes=[
                GraphNode(id="run", op="skill.invoke", config={"skill_id": "dev.run_command.v1", "version": "1.0.0"}),
                GraphNode(id="starts_with", op="skill.invoke", config={"skill_id": generated_spec.skill_id, "version": "1.0.0"}),
            ],
            edges=[
                GraphEdge(from_="input.argv", to="run.argv"),
                GraphEdge(from_="input.cwd", to="run.cwd"),
                GraphEdge(from_="run.stdout", to="starts_with.text"),
                GraphEdge(from_="input.prefix", to="starts_with.prefix"),
            ],
            outputs={"result": "starts_with.result"},
        ),
    )


def _build_read_replace_write_plan(
    goal: str,
    registry: RegistryBackend,
    generated_spec: SkillSpec,
) -> GlueGraph | None:
    from graphsmith.models.common import IOField
    from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode

    available = {entry.id for entry in registry.list_all()} if hasattr(registry, "list_all") else set()
    if not {"fs.read_text.v1", "fs.write_text.v1", generated_spec.skill_id}.issubset(available):
        return None
    if generated_spec.skill_id != "text.replace.v1":
        return None
    return GlueGraph(
        goal=goal,
        inputs=[
            IOField(name="input_path", type="string"),
            IOField(name="output_path", type="string"),
            IOField(name="old", type="string"),
            IOField(name="new", type="string"),
        ],
        outputs=[IOField(name="path", type="string")],
        effects=["filesystem_read", "filesystem_write", "pure"],
        graph=GraphBody(
            version=1,
            nodes=[
                GraphNode(id="read", op="skill.invoke", config={"skill_id": "fs.read_text.v1", "version": "1.0.0"}),
                GraphNode(id="replace", op="skill.invoke", config={"skill_id": generated_spec.skill_id, "version": "1.0.0"}),
                GraphNode(id="write", op="skill.invoke", config={"skill_id": "fs.write_text.v1", "version": "1.0.0"}),
            ],
            edges=[
                GraphEdge(from_="input.input_path", to="read.path"),
                GraphEdge(from_="read.text", to="replace.text"),
                GraphEdge(from_="input.old", to="replace.old"),
                GraphEdge(from_="input.new", to="replace.new"),
                GraphEdge(from_="input.output_path", to="write.path"),
                GraphEdge(from_="replace.replaced", to="write.text"),
            ],
            outputs={"path": "write.path"},
        ),
    )


def _build_loop_read_contains_plan(
    goal: str,
    registry: RegistryBackend,
    generated_spec: SkillSpec,
) -> GlueGraph | None:
    if generated_spec.skill_id != "text.contains.v1":
        return None

    available = {entry.id for entry in registry.list_all()} if hasattr(registry, "list_all") else set()
    if not {"fs.read_text.v1", generated_spec.skill_id}.issubset(available):
        return None

    ir = PlanningIR(
        goal=goal,
        inputs=[
            IRInput(name="paths", type="array<string>"),
            IRInput(name="substring", type="string"),
        ],
        steps=[],
        blocks=[
            IRBlock(
                name="process_each_file",
                kind="loop",
                collection=IRSource(step="input", port="paths"),
                inputs={
                    "path": IRSource(binding="item"),
                    "substring": IRSource(step="input", port="substring"),
                },
                steps=[
                    IRStep(
                        name="read",
                        skill_id="fs.read_text.v1",
                        sources={"path": IRSource(step="input", port="path")},
                    ),
                    IRStep(
                        name="contains",
                        skill_id=generated_spec.skill_id,
                        sources={
                            "text": IRSource(step="read", port="text"),
                            "substring": IRSource(step="input", port="substring"),
                        },
                    ),
                ],
                final_outputs={"result": IROutputRef(step="contains", port="result")},
                max_items=50,
            )
        ],
        final_outputs={"result": IROutputRef(step="process_each_file", port="result")},
        effects=["filesystem_read", "pure"],
    )
    return compile_ir(ir)


def _build_environment_fallback_plan(
    goal: str,
    registry: RegistryBackend,
    generated_spec: SkillSpec | None = None,
) -> GlueGraph | None:
    if _goal_matches_pytest_prefix_branch(goal):
        return _build_run_pytest_prefix_branch_plan(goal, registry)
    if _goal_matches_read_normalize_write(goal):
        return _build_read_normalize_write_plan(goal, registry)
    if _goal_matches_read_normalize(goal):
        return _build_read_normalize_plan(goal, registry)
    if _goal_matches_run_pytest(goal):
        return _build_run_pytest_plan(goal, registry)
    if generated_spec is not None and _goal_matches_loop_read_contains(goal):
        return _build_loop_read_contains_plan(goal, registry, generated_spec)
    if generated_spec is not None and _goal_matches_run_command_starts_with(goal):
        return _build_run_command_starts_with_plan(goal, registry, generated_spec)
    if generated_spec is not None and _goal_matches_read_replace_write(goal):
        return _build_read_replace_write_plan(goal, registry, generated_spec)
    return None


def _build_sentiment_branch_fallback_plan(goal: str, registry: RegistryBackend) -> GlueGraph | None:
    """Build a bounded branch fallback for sentiment-conditioned prefix formatting."""
    return _build_sentiment_branch_formatter_plan(goal, registry)


def _build_sentiment_branch_formatter_plan(
    goal: str,
    registry: RegistryBackend,
    *,
    positive_body_skill_id: str | None = None,
    negative_body_skill_id: str | None = None,
) -> GlueGraph | None:
    """Build a bounded sentiment-gated branch with optional per-branch body skills."""
    from graphsmith.models.common import IOField
    from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode

    if positive_body_skill_id is None and negative_body_skill_id is None:
        if not _goal_matches_sentiment_branch_prefix(goal):
            return None
    else:
        if not _goal_matches_sentiment_branch_body_prefix(goal):
            return None

    required = {"text.classify_sentiment.v1", "text.prefix_lines.v1"}
    if positive_body_skill_id:
        required.add(positive_body_skill_id)
    if negative_body_skill_id:
        required.add(negative_body_skill_id)
    available = {entry.id for entry in registry.list_all()} if hasattr(registry, "list_all") else set()
    if not required.issubset(available):
        return None

    def _single_output_port(skill_id: str) -> str | None:
        entry = _find_registry_entry(registry, skill_id)
        if entry is None:
            return None
        try:
            pkg = registry.fetch(entry.id, entry.version)
        except Exception:
            return None
        if len(pkg.skill.outputs) != 1:
            return None
        return pkg.skill.outputs[0].name

    effects = {"llm_inference", "pure"}
    nodes: list[GraphNode] = [
        GraphNode(id="classify", op="skill.invoke", config={"skill_id": "text.classify_sentiment.v1", "version": "1.0.0"}),
        GraphNode(id="positive_label", op="template.render", config={"template": "positive"}),
        GraphNode(id="is_positive", op="text.equals"),
    ]
    edges: list[GraphEdge] = [
        GraphEdge(from_="input.text", to="classify.text"),
        GraphEdge(from_="classify.sentiment", to="is_positive.text"),
        GraphEdge(from_="positive_label.rendered", to="is_positive.other"),
    ]

    positive_text_source = "input.text"
    negative_text_source = "input.text"

    if positive_body_skill_id is not None:
        positive_port = _single_output_port(positive_body_skill_id)
        if positive_port is None:
            return None
        nodes.append(
            GraphNode(
                id="positive_body",
                op="skill.invoke",
                config={"skill_id": positive_body_skill_id, "version": "1.0.0"},
                when="is_positive.result",
            )
        )
        edges.append(GraphEdge(from_="input.text", to="positive_body.text"))
        positive_text_source = f"positive_body.{positive_port}"

    if negative_body_skill_id is not None:
        negative_port = _single_output_port(negative_body_skill_id)
        if negative_port is None:
            return None
        nodes.append(
            GraphNode(
                id="negative_body",
                op="skill.invoke",
                config={"skill_id": negative_body_skill_id, "version": "1.0.0"},
                when="!is_positive.result",
            )
        )
        edges.append(GraphEdge(from_="input.text", to="negative_body.text"))
        negative_text_source = f"negative_body.{negative_port}"

    nodes.extend(
        [
            GraphNode(
                id="prefix_positive",
                op="skill.invoke",
                config={"skill_id": "text.prefix_lines.v1", "version": "1.0.0"},
                when="is_positive.result",
            ),
            GraphNode(
                id="prefix_negative",
                op="skill.invoke",
                config={"skill_id": "text.prefix_lines.v1", "version": "1.0.0"},
                when="!is_positive.result",
            ),
            GraphNode(id="merge_prefixed", op="fallback.try"),
        ]
    )
    edges.extend(
        [
            GraphEdge(from_=positive_text_source, to="prefix_positive.text"),
            GraphEdge(from_="input.positive_prefix", to="prefix_positive.prefix"),
            GraphEdge(from_=negative_text_source, to="prefix_negative.text"),
            GraphEdge(from_="input.negative_prefix", to="prefix_negative.prefix"),
            GraphEdge(from_="prefix_positive.prefixed", to="merge_prefixed.primary"),
            GraphEdge(from_="prefix_negative.prefixed", to="merge_prefixed.fallback"),
        ]
    )

    return GlueGraph(
        goal=goal,
        inputs=[
            IOField(name="text", type="string"),
            IOField(name="positive_prefix", type="string"),
            IOField(name="negative_prefix", type="string"),
        ],
        outputs=[IOField(name="prefixed", type="string")],
        effects=sorted(effects),
        graph=GraphBody(
            version=1,
            nodes=nodes,
            edges=edges,
            outputs={"prefixed": "merge_prefixed.result"},
        ),
    )


def _build_sentiment_branch_body_fallback_plan(goal: str, registry: RegistryBackend) -> GlueGraph | None:
    """Build a bounded branch fallback with distinct per-branch body skills."""
    return _build_sentiment_branch_formatter_plan(
        goal,
        registry,
        positive_body_skill_id="text.summarize.v1",
        negative_body_skill_id="text.extract_keywords.v1",
    )


def _sample_input_value(field_name: str, field_type: Any) -> Any:
    """Build a deterministic smoke-test value for a graph input."""
    type_str = field_type if isinstance(field_type, str) else ""
    if field_name == "raw_json":
        return '{"value": "alpha"}'
    if field_name == "substring":
        return "alpha"
    if field_name == "prefix":
        return "# "
    if field_name == "positive_prefix":
        return "+ "
    if field_name == "negative_prefix":
        return "- "
    if field_name == "divisor":
        return "2"
    if field_name == "values":
        return "1\n2\n3\n4"
    if field_name in {"text", "code_lines"}:
        return "Alpha\nBeta"
    if field_name == "texts":
        return ["Alpha text", "Beta text"]
    if field_name == "json_objects":
        return ['{"value":"alpha"}', '{"value":"beta"}']

    if type_str.startswith("array<number>"):
        return [1, 2, 3]
    if type_str.startswith("array<string>"):
        return ["alpha", "beta"]
    if type_str == "number":
        return 1.5
    if type_str == "integer":
        return 1
    if type_str == "boolean":
        return True
    if type_str == "object":
        return {"value": "alpha"}
    return "sample"


def _build_single_skill_invoke_plan(
    goal: str,
    skill_id: str,
    inputs: list[Any],
    outputs: list[Any],
    effects: list[str],
) -> GlueGraph:
    from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode

    return GlueGraph(
        goal=goal,
        inputs=inputs,
        outputs=outputs,
        effects=effects,
        graph=GraphBody(
            version=1,
            nodes=[GraphNode(id="synthesized", op="skill.invoke", config={"skill_id": skill_id, "version": "1.0.0"})],
            edges=[
                GraphEdge(from_=f"input.{field.name}", to=f"synthesized.{field.name}")
                for field in inputs
            ],
            outputs={field.name: f"synthesized.{field.name}" for field in outputs},
        ),
    )


def _synthesize_subgraph_skill(
    goal: str,
    graph: GlueGraph,
    registry: RegistryBackend,
    *,
    output_dir: str | Path | None = None,
) -> tuple[GlueGraph | None, str, str]:
    """Materialize a composed graph as a reusable skill package and invoke plan."""
    from graphsmith.models.common import ExampleCase
    from graphsmith.models.package import ExamplesFile, SkillPackage
    from graphsmith.models.skill import SkillMetadata
    from graphsmith.ops.llm_provider import EchoLLMProvider
    from graphsmith.runtime import run_skill_package
    from graphsmith.validator import validate_skill_package

    graph_dump = json.dumps(graph.model_dump(mode="json"), sort_keys=True)
    digest = hashlib.sha1(graph_dump.encode("utf-8")).hexdigest()[:8]
    slug = "".join(c if c.isalnum() else "_" for c in goal.lower()).strip("_")[:24] or "workflow"
    skill_id = f"synth.{slug}_{digest}.v1"

    existing = _find_registry_entry(registry, skill_id)
    if existing is not None:
        return (
            _build_single_skill_invoke_plan(goal, skill_id, graph.inputs, graph.outputs, graph.effects),
            skill_id,
            "",
        )

    pkg = glue_to_skill_package(graph)
    pkg = SkillPackage(
        root_path="(synthesized)",
        skill=SkillMetadata(
            id=skill_id,
            name=f"Synthesized {skill_id.split('.', 1)[1].rsplit('.v', 1)[0].replace('_', ' ').title()}",
            version="1.0.0",
            description=f"Synthesized subgraph skill for goal: {goal}",
            inputs=graph.inputs,
            outputs=graph.outputs,
            effects=graph.effects,
            tags=["synthesized", "subgraph", "closed-loop"],
            authors=["graphsmith"],
        ),
        graph=pkg.graph,
        examples=ExamplesFile(),
    )
    validate_skill_package(pkg)

    sample_inputs = {
        field.name: _sample_input_value(field.name, field.type)
        for field in pkg.skill.inputs
    }
    smoke = run_skill_package(
        pkg,
        sample_inputs,
        registry=registry,
        llm_provider=EchoLLMProvider(prefix=""),
    )
    pkg = pkg.model_copy(
        update={
            "examples": ExamplesFile(
                examples=[
                    ExampleCase(
                        name="smoke",
                        input=sample_inputs,
                        expected_output=smoke.outputs,
                    )
                ]
            )
        }
    )

    synth_root = Path(output_dir) if output_dir else Path(tempfile.mkdtemp()) / "synthesized_skills"
    synth_root.mkdir(parents=True, exist_ok=True)
    skill_dir = synth_root / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "skill.yaml").write_text(
        yaml.safe_dump(pkg.skill.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    (skill_dir / "graph.yaml").write_text(
        yaml.safe_dump(pkg.graph.model_dump(mode="json", by_alias=True), sort_keys=False),
        encoding="utf-8",
    )
    (skill_dir / "examples.yaml").write_text(
        yaml.safe_dump(pkg.examples.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )

    registry.publish(str(skill_dir))
    return (
        _build_single_skill_invoke_plan(goal, skill_id, graph.inputs, graph.outputs, graph.effects),
        skill_id,
        str(skill_dir),
    )


def _graph_skill_ids(graph: GlueGraph) -> list[str]:
    skill_ids: list[str] = []
    body = getattr(graph, "graph", None)
    nodes = getattr(body, "nodes", None)
    if not nodes:
        return skill_ids
    for node in nodes:
        if node.op == "skill.invoke" and isinstance(node.config, dict):
            skill_id = node.config.get("skill_id")
            if isinstance(skill_id, str):
                skill_ids.append(skill_id)
        else:
            skill_ids.append(node.op)
    return skill_ids


def _maybe_synthesize_fallback_graph(
    goal: str,
    graph: GlueGraph,
    result: ClosedLoopResult,
    registry: RegistryBackend,
    *,
    output_dir: str | Path | None = None,
) -> GlueGraph:
    if len(graph.graph.nodes) <= 1:
        return graph
    if any(effect in {"filesystem_read", "filesystem_write", "shell_exec"} for effect in graph.effects):
        return graph
    synthesized_plan, synthesized_skill_id, synthesis_dir = _synthesize_subgraph_skill(
        goal,
        graph,
        registry,
        output_dir=output_dir,
    )
    if synthesized_plan is None:
        return graph
    result.synthesized_skill_id = synthesized_skill_id
    result.synthesis_dir = synthesis_dir
    return synthesized_plan


def _exact_skill_grounding_failure(
    graph: GlueGraph | None,
    spec: SkillSpec | None,
) -> str:
    """Detect when a plan is executable but misses the exact requested capability."""
    if graph is None or spec is None:
        return ""

    skill_ids = set(_graph_skill_ids(graph))
    if not skill_ids:
        return ""
    if spec.skill_id not in skill_ids:
        return f"missing_exact_skill:{spec.skill_id}"

    graph_inputs = {field.name for field in graph.inputs}
    missing_inputs = [
        inp["name"]
        for inp in spec.inputs
        if inp.get("required", True) and inp["name"] not in graph_inputs
    ]
    if missing_inputs:
        return "missing_exact_skill_inputs:" + ",".join(sorted(missing_inputs))

    return ""


def _existing_skill_grounding_failure(
    graph: GlueGraph | None,
    goal: str,
) -> str:
    """Detect when a deterministic existing-skill chain picked the wrong existing capability."""
    if graph is None:
        return ""
    expected = _expected_existing_skill_ids(goal)
    if len(expected) < 2:
        return ""
    skill_ids = set(_graph_skill_ids(graph))
    missing = [skill_id for skill_id in expected if skill_id not in skill_ids]
    if missing:
        return "missing_existing_skills:" + ",".join(missing)
    return ""


def _branch_region_grounding_failure(
    graph: GlueGraph | None,
    goal: str,
) -> str:
    """Detect branch-region plans that are missing required public inputs or canonical structure."""
    if graph is None:
        return ""
    if not (
        _goal_matches_sentiment_branch_prefix(goal)
        or _goal_matches_sentiment_branch_body_prefix(goal)
    ):
        return ""

    graph_inputs = {field.name for field in graph.inputs}
    required_inputs = {"text", "positive_prefix", "negative_prefix"}
    missing_inputs = sorted(required_inputs - graph_inputs)
    if missing_inputs:
        return "missing_branch_inputs:" + ",".join(missing_inputs)

    skill_ids = set(_graph_skill_ids(graph))
    required_skill_ids = {"text.classify_sentiment.v1", "text.prefix_lines.v1", "fallback.try"}
    if _goal_matches_sentiment_branch_body_prefix(goal):
        required_skill_ids.update({"text.summarize.v1", "text.extract_keywords.v1"})
    missing_skill_ids = sorted(skill_id for skill_id in required_skill_ids if skill_id not in skill_ids)
    if missing_skill_ids:
        return "missing_branch_skills:" + ",".join(missing_skill_ids)

    return ""


def _environment_workflow_grounding_failure(
    graph: GlueGraph | None,
    goal: str,
) -> str:
    """Detect environment workflow plans that miss required skills, inputs, or outputs."""
    if graph is None:
        return ""

    required_skill_ids: set[str] = set()
    required_inputs: set[str] = set()
    required_outputs: set[str] = set()

    if _goal_matches_read_normalize_write(goal):
        required_skill_ids = {"fs.read_text.v1", "text.normalize.v1", "fs.write_text.v1"}
        required_inputs = {"input_path", "output_path"}
        required_outputs = {"path"}
    elif _goal_matches_read_normalize(goal):
        required_skill_ids = {"fs.read_text.v1", "text.normalize.v1"}
        required_inputs = {"path"}
        required_outputs = {"normalized"}
    elif _goal_matches_run_pytest(goal):
        required_skill_ids = {"dev.run_pytest.v1"}
        required_inputs = {"cwd"}
        required_outputs = {"stdout"}
    elif _goal_matches_pytest_prefix_branch(goal):
        required_skill_ids = {"dev.run_pytest.v1", "text.prefix_lines.v1", "fallback.try"}
        required_inputs = {"cwd"}
        required_outputs = {"prefixed"}
    elif _goal_matches_run_command_starts_with(goal):
        required_skill_ids = {"dev.run_command.v1", "text.starts_with.v1"}
        required_inputs = {"argv", "cwd", "prefix"}
        required_outputs = {"result"}
    elif _goal_matches_read_replace_write(goal):
        required_skill_ids = {"fs.read_text.v1", "text.replace.v1", "fs.write_text.v1"}
        required_inputs = {"input_path", "output_path", "old", "new"}
        required_outputs = {"path"}
    elif _goal_matches_loop_read_contains(goal):
        required_skill_ids = {"parallel.map"}
        required_inputs = {"paths", "substring"}
        required_outputs = {"result"}
    else:
        return ""

    graph_inputs = {field.name for field in graph.inputs}
    missing_inputs = sorted(required_inputs - graph_inputs)
    if missing_inputs:
        return "missing_environment_inputs:" + ",".join(missing_inputs)

    graph_outputs = {field.name for field in graph.outputs}
    missing_outputs = sorted(required_outputs - graph_outputs)
    if missing_outputs:
        return "missing_environment_outputs:" + ",".join(missing_outputs)

    skill_ids = set(_graph_skill_ids(graph))
    missing_skills = sorted(required_skill_ids - skill_ids)
    if missing_skills:
        return "missing_environment_skills:" + ",".join(missing_skills)

    return ""


# ── Orchestrator ─────────────────────────────────────────────────


def run_closed_loop(
    goal: str,
    backend: Any,
    registry: RegistryBackend,
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
    from graphsmith.planner.graph_repair import normalize_glue_graph_contracts

    result = ClosedLoopResult()
    generated_registered = False

    # ── Step 1: Initial plan attempt ──────────────────────────────
    exact_spec: SkillSpec | None = None
    try:
        exact_spec = extract_spec(goal)
    except AutogenError:
        exact_spec = None
    if exact_spec is None and _goal_matches_read_replace_write(goal):
        exact_spec = _spec_from_template("replace", goal)
    if exact_spec is None and _goal_matches_run_command_starts_with(goal):
        exact_spec = _spec_from_template("starts_with", goal)
    if exact_spec is None and _goal_matches_loop_read_contains(goal):
        exact_spec = _spec_from_template("contains", goal)
    if exact_spec is not None and _autogen_conflicts_with_existing_pipeline(goal, exact_spec):
        exact_spec = None

    cands = retrieve_candidates(goal, registry)
    cands = filter_candidates_by_goal_policy(cands, goal)
    if exact_spec is not None:
        cands = _prepend_exact_skill_candidate(cands, registry, exact_spec.skill_id)
        cands = filter_candidates_by_goal_policy(cands, goal)
    request = PlanRequest(goal=goal, candidates=cands, constraints=derive_goal_constraints(goal))
    plan_result = backend.compose(request)
    if plan_result.graph is not None:
        normalized_graph, _ = normalize_glue_graph_contracts(plan_result.graph, registry=registry)
        plan_result = plan_result.model_copy(update={"graph": normalized_graph})
    plan_grounding_failure = _exact_skill_grounding_failure(plan_result.graph, exact_spec)
    existing_grounding_failure = _existing_skill_grounding_failure(plan_result.graph, goal)
    branch_grounding_failure = _branch_region_grounding_failure(plan_result.graph, goal)
    environment_grounding_failure = _environment_workflow_grounding_failure(plan_result.graph, goal)

    result.initial_status = plan_result.status
    result.initial_plan = plan_result.graph

    if plan_result.status == "success" and plan_result.graph is not None:
        block_reason = _semantic_fidelity_block_reason(goal)
        if block_reason:
            result.stopped_reason = block_reason
            result.success = False
            return result
    if (
        plan_result.status == "success"
        and plan_result.graph is not None
        and not plan_grounding_failure
        and not existing_grounding_failure
        and not branch_grounding_failure
        and not environment_grounding_failure
    ):
        result.stopped_reason = "initial_plan_succeeded"
        result.success = True
        return result

    environment_fallback = _build_environment_fallback_plan(goal, registry, exact_spec)
    if environment_fallback is not None:
        environment_fallback = _maybe_synthesize_fallback_graph(
            goal,
            environment_fallback,
            result,
            registry,
            output_dir=output_dir,
        )
        result.replan_status = "success"
        result.replan_plan = environment_fallback
        block_reason = _semantic_fidelity_block_reason(goal)
        if block_reason:
            result.stopped_reason = block_reason
            result.success = False
            return result
        result.stopped_reason = "environment_fallback_succeeded"
        result.success = True
        return result

    branch_fallback = _build_sentiment_branch_body_fallback_plan(goal, registry)
    if branch_fallback is None:
        branch_fallback = _build_sentiment_branch_fallback_plan(goal, registry)
    if branch_fallback is not None:
        if _goal_matches_sentiment_branch_body_prefix(goal):
            synthesized_plan, synthesized_skill_id, synthesis_dir = _synthesize_subgraph_skill(
                goal,
                branch_fallback,
                registry,
                output_dir=output_dir,
            )
            if synthesized_plan is not None:
                branch_fallback = synthesized_plan
                result.synthesized_skill_id = synthesized_skill_id
                result.synthesis_dir = synthesis_dir
        result.replan_status = "success"
        result.replan_plan = branch_fallback
        block_reason = _semantic_fidelity_block_reason(goal)
        if block_reason:
            result.stopped_reason = block_reason
            result.success = False
            return result
        result.stopped_reason = "branch_fallback_succeeded"
        result.success = True
        return result

    if existing_grounding_failure and not _goal_supports_structured_numeric_fallback(goal):
        existing_fallback = _build_existing_skill_fallback_plan(goal, registry)
        if existing_fallback is not None:
            result.replan_status = "success"
            result.replan_plan = existing_fallback
            block_reason = _semantic_fidelity_block_reason(goal)
            if block_reason:
                result.stopped_reason = block_reason
                result.success = False
                return result
            result.stopped_reason = "existing_pipeline_fallback_succeeded"
            result.success = True
            return result

    if exact_spec is not None:
        loop_fallback = _build_loop_fallback_plan(goal, registry, exact_spec)
        if loop_fallback is not None:
            result.replan_status = "success"
            result.replan_plan = loop_fallback
            block_reason = _semantic_fidelity_block_reason(goal)
            if block_reason:
                result.stopped_reason = block_reason
                result.success = False
                return result
            result.stopped_reason = "loop_fallback_succeeded"
            result.success = True
            return result

    if _goal_supports_structured_numeric_fallback(goal):
        goal_keys = [key for key in match_template_keys(goal) if key in {"median", "max", "min", "divide", "contains"}]
        generated_specs = [_spec_from_template(key, goal) for key in goal_keys]
        registered_specs: list[SkillSpec] = []
        try:
            gen_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp()) / "generated_skills"
            gen_dir.mkdir(parents=True, exist_ok=True)
            for spec in generated_specs:
                if _find_registry_entry(registry, spec.skill_id) is not None:
                    continue
                skill_dir = generate_skill_files(spec, gen_dir)
                val_result = validate_and_test(spec, skill_dir)
                if not (
                    val_result["validation"] == "PASS"
                    and val_result["examples_passed"] == val_result["examples_total"]
                ):
                    break
                register_generated_op(spec)
                registered_specs.append(spec)
                registry.publish(str(skill_dir))
            else:
                fallback_graph = _build_structured_numeric_fallback_plan(goal, registry, generated_specs)
                if fallback_graph is not None:
                    synthesized_plan, synthesized_skill_id, synthesis_dir = _synthesize_subgraph_skill(
                        goal,
                        fallback_graph,
                        registry,
                        output_dir=output_dir,
                    )
                    if synthesized_plan is not None:
                        fallback_graph = synthesized_plan
                        result.synthesized_skill_id = synthesized_skill_id
                        result.synthesis_dir = synthesis_dir
                    result.generated_spec = generated_specs[0] if generated_specs else None
                    result.replan_status = "success"
                    result.replan_plan = fallback_graph
                    block_reason = _semantic_fidelity_block_reason(goal)
                    if block_reason:
                        result.stopped_reason = block_reason
                        result.success = False
                        return result
                    result.stopped_reason = "structured_numeric_fallback_succeeded"
                    result.success = True
                    return result
        finally:
            for spec in reversed(registered_specs):
                unregister_generated_op(spec)

    if _goal_supports_two_generated_linear_fallback(goal):
        generated_specs = [
            _spec_from_template("uppercase", goal),
            _spec_from_template("starts_with", goal),
        ]
        generated_dirs: list[Path] = []
        registered_specs: list[SkillSpec] = []
        try:
            gen_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp()) / "generated_skills"
            gen_dir.mkdir(parents=True, exist_ok=True)
            for spec in generated_specs:
                skill_dir = generate_skill_files(spec, gen_dir)
                generated_dirs.append(skill_dir)
                val_result = validate_and_test(spec, skill_dir)
                if not (
                    val_result["validation"] == "PASS"
                    and val_result["examples_passed"] == val_result["examples_total"]
                ):
                    break
                register_generated_op(spec)
                registered_specs.append(spec)
                registry.publish(str(skill_dir))
            else:
                fallback_graph = _build_two_generated_linear_fallback_plan(goal, registry, generated_specs)
                if fallback_graph is not None:
                    result.generated_spec = generated_specs[0]
                    result.replan_status = "success"
                    result.replan_plan = fallback_graph
                    block_reason = _semantic_fidelity_block_reason(goal)
                    if block_reason:
                        result.stopped_reason = block_reason
                        result.success = False
                        return result
                    result.stopped_reason = "two_generated_fallback_succeeded"
                    result.success = True
                    return result
        finally:
            for spec in reversed(registered_specs):
                unregister_generated_op(spec)

    # ── Step 2: Detect missing skill ──────────────────────────────
    diagnosis = detect_missing_skill(goal, plan_result, backend.last_candidates)
    available_ids = {f"{entry.id}" for entry in cands}
    if hasattr(registry, "list_all"):
        try:
            available_ids.update(entry.id for entry in registry.list_all())
        except Exception:
            pass
    if exact_spec is not None and _goal_supports_environment_fallback(goal) and exact_spec.skill_id not in available_ids:
        diagnosis = MissingSkillDiagnosis(
            is_missing=True,
            reason=f"Environment workflow requires missing generated skill {exact_spec.skill_id}",
            capability_hint=goal,
            exact_skill_id=exact_spec.skill_id,
        )
    else:
        diagnosis = detect_missing_skill(
            goal,
            plan_result if not plan_grounding_failure and not existing_grounding_failure else PlanResult(status="failure", graph=plan_result.graph),
            backend.last_candidates,
            available_skill_ids=available_ids,
        )
    if plan_grounding_failure:
        diagnosis.reason = f"{diagnosis.reason}; initial plan mismatch: {plan_grounding_failure}"
    if existing_grounding_failure:
        diagnosis.reason = f"{diagnosis.reason}; initial plan mismatch: {existing_grounding_failure}"
    if branch_grounding_failure:
        diagnosis.reason = f"{diagnosis.reason}; initial plan mismatch: {branch_grounding_failure}"
    if environment_grounding_failure:
        diagnosis.reason = f"{diagnosis.reason}; initial plan mismatch: {environment_grounding_failure}"
    result.detected_missing = diagnosis.is_missing
    result.diagnosis_reason = diagnosis.reason

    if diagnosis.reusable_existing_skill and diagnosis.exact_skill_id:
        cands = retrieve_candidates(goal, registry)
        cands = filter_candidates_by_goal_policy(cands, goal)
        cands = _prepend_exact_skill_candidate(cands, registry, diagnosis.exact_skill_id)
        cands = filter_candidates_by_goal_policy(cands, goal)
        retry_request = PlanRequest(
            goal=goal,
            candidates=cands,
            constraints=derive_goal_constraints(goal),
        )
        retry_result = backend.compose(retry_request)
        retry_grounding_failure = _exact_skill_grounding_failure(retry_result.graph, exact_spec)
        result.replan_status = retry_result.status
        result.replan_plan = retry_result.graph
        if (
            retry_result.status == "success"
            and retry_result.graph is not None
            and not retry_grounding_failure
        ):
            block_reason = _semantic_fidelity_block_reason(goal)
            if block_reason:
                result.stopped_reason = block_reason
                result.success = False
                return result
            result.stopped_reason = "existing_skill_replan_succeeded"
            result.success = True
            return result
        if exact_spec is not None:
            environment_fallback = _build_environment_fallback_plan(goal, registry, exact_spec)
            if environment_fallback is not None:
                environment_fallback = _maybe_synthesize_fallback_graph(
                    goal,
                    environment_fallback,
                    result,
                    registry,
                    output_dir=output_dir,
                )
                result.replan_status = "success"
                result.replan_plan = environment_fallback
                block_reason = _semantic_fidelity_block_reason(goal)
                if block_reason:
                    result.stopped_reason = block_reason
                    result.success = False
                    return result
                result.stopped_reason = "environment_fallback_succeeded"
                result.success = True
                return result
        if exact_spec is not None and not _is_multi_stage_goal(goal):
            result.replan_status = "success"
            result.replan_plan = _build_single_skill_plan(goal, exact_spec)
            block_reason = _semantic_fidelity_block_reason(goal)
            if block_reason:
                result.stopped_reason = block_reason
                result.success = False
                return result
            result.stopped_reason = "single_skill_fallback_succeeded"
            result.success = True
            return result
        if exact_spec is not None:
            fallback_graph = _build_multi_stage_fallback_plan(goal, registry, exact_spec)
            if fallback_graph is not None:
                result.replan_status = "success"
                result.replan_plan = fallback_graph
                block_reason = _semantic_fidelity_block_reason(goal)
                if block_reason:
                    result.stopped_reason = block_reason
                    result.success = False
                    return result
                result.stopped_reason = "multi_stage_fallback_succeeded"
                result.success = True
                return result
        result.stopped_reason = "existing_skill_replan_failed"
        return result

    if not diagnosis.is_missing:
        existing_fallback = _build_existing_skill_fallback_plan(goal, registry)
        if existing_fallback is not None:
            result.replan_status = "success"
            result.replan_plan = existing_fallback
            block_reason = _semantic_fidelity_block_reason(goal)
            if block_reason:
                result.stopped_reason = block_reason
                result.success = False
                return result
            result.stopped_reason = "existing_pipeline_fallback_succeeded"
            result.success = True
            return result
        result.stopped_reason = "missing_skill_not_detected"
        return result

    # ── Step 3: Generate candidate skill ──────────────────────────
    if exact_spec is not None and diagnosis.exact_skill_id == exact_spec.skill_id:
        spec = exact_spec
    else:
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
        cands = filter_candidates_by_goal_policy(cands, goal)
        cands = _prepend_exact_skill_candidate(cands, registry, spec.skill_id)
        cands = filter_candidates_by_goal_policy(cands, goal)
        request = PlanRequest(
            goal=goal,
            candidates=cands,
            constraints=derive_goal_constraints(goal),
        )
        replan_result = backend.compose(request)
        replan_grounding_failure = _exact_skill_grounding_failure(replan_result.graph, spec)

        result.replan_status = replan_result.status
        result.replan_plan = replan_result.graph
        result.success = (
            replan_result.status == "success"
            and replan_result.graph is not None
            and not replan_grounding_failure
        )
        if result.success:
            block_reason = _semantic_fidelity_block_reason(goal)
            if block_reason:
                result.stopped_reason = block_reason
                result.success = False
                return result
            result.stopped_reason = "replan_succeeded"
            return result
        environment_fallback = _build_environment_fallback_plan(goal, registry, spec)
        if environment_fallback is not None:
            environment_fallback = _maybe_synthesize_fallback_graph(
                goal,
                environment_fallback,
                result,
                registry,
                output_dir=output_dir,
            )
            result.replan_status = "success"
            result.replan_plan = environment_fallback
            block_reason = _semantic_fidelity_block_reason(goal)
            if block_reason:
                result.stopped_reason = block_reason
                result.success = False
                return result
            result.stopped_reason = "environment_fallback_succeeded"
            result.success = True
            return result
        if not _is_multi_stage_goal(goal):
            result.replan_status = "success"
            result.replan_plan = _build_single_skill_plan(goal, spec)
            block_reason = _semantic_fidelity_block_reason(goal)
            if block_reason:
                result.stopped_reason = block_reason
                result.success = False
                return result
            result.stopped_reason = "single_skill_fallback_succeeded"
            result.success = True
            return result
        fallback_graph = _build_multi_stage_fallback_plan(goal, registry, spec)
        if fallback_graph is not None:
            result.replan_status = "success"
            result.replan_plan = fallback_graph
            block_reason = _semantic_fidelity_block_reason(goal)
            if block_reason:
                result.stopped_reason = block_reason
                result.success = False
                return result
            result.stopped_reason = "multi_stage_fallback_succeeded"
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
    if result.synthesized_skill_id:
        lines.append(f"  Synthesized subgraph: {result.synthesized_skill_id}")
        if result.synthesis_dir:
            lines.append(f"  Synthesized files: {result.synthesis_dir}")

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
