"""Deterministic IR → GlueGraph compiler.

Lowers a PlanningIR into a fully-formed GlueGraph by generating
node IDs, edges, config embedding, and graph_outputs mapping.
All decisions are deterministic — no LLM involvement.
"""
from __future__ import annotations

import re
from typing import Any

from graphsmith.constants import ALLOWED_EFFECTS, ALLOWED_TYPES, PRIMITIVE_OPS
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.planner.ir import IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.models import GlueGraph


# ── Compiler errors ─────────────────────────────────────────────────


class CompilerError(Exception):
    """Base class for deterministic compiler errors."""

    def __init__(self, message: str, *, phase: str, details: dict[str, Any] | None = None) -> None:
        self.phase = phase
        self.details = details or {}
        super().__init__(message)


class DuplicateStepError(CompilerError):
    """Two steps share the same name."""

    def __init__(self, step_name: str) -> None:
        super().__init__(
            f"Duplicate step name: '{step_name}'",
            phase="validate_ir",
            details={"step_name": step_name},
        )


class UnknownSourceStepError(CompilerError):
    """A source references a step that doesn't exist."""

    def __init__(self, step_name: str, source_port: str, ref_step: str) -> None:
        super().__init__(
            f"Step '{step_name}' input '{source_port}' references unknown step '{ref_step}'",
            phase="validate_ir",
            details={"step_name": step_name, "source_port": source_port, "ref_step": ref_step},
        )


class UnknownOutputStepError(CompilerError):
    """A final_output references a step that doesn't exist."""

    def __init__(self, output_name: str, ref_step: str) -> None:
        super().__init__(
            f"Output '{output_name}' references unknown step '{ref_step}'",
            phase="validate_ir",
            details={"output_name": output_name, "ref_step": ref_step},
        )


class UnknownInputError(CompilerError):
    """A source references a graph input that doesn't exist."""

    def __init__(self, step_name: str, source_port: str, input_name: str) -> None:
        super().__init__(
            f"Step '{step_name}' input '{source_port}' references undeclared input '{input_name}'",
            phase="validate_ir",
            details={"step_name": step_name, "source_port": source_port, "input_name": input_name},
        )


class InvalidEffectError(CompilerError):
    """An effect is not in the allowed set."""

    def __init__(self, effect: str) -> None:
        super().__init__(
            f"Invalid effect: '{effect}'",
            phase="validate_ir",
            details={"effect": effect, "allowed": sorted(ALLOWED_EFFECTS)},
        )


class EmptyStepsError(CompilerError):
    """IR has no steps."""

    def __init__(self) -> None:
        super().__init__("IR has no steps", phase="validate_ir")


class SelfLoopError(CompilerError):
    """A step sources from itself."""

    def __init__(self, step_name: str, source_port: str) -> None:
        super().__init__(
            f"Step '{step_name}' input '{source_port}' references itself (self-loop)",
            phase="validate_ir",
            details={"step_name": step_name, "source_port": source_port},
        )


class CycleError(CompilerError):
    """The step dependency graph contains a cycle."""

    def __init__(self, involved: list[str]) -> None:
        super().__init__(
            f"Cycle detected among steps: {', '.join(involved)}",
            phase="validate_ir",
            details={"steps": involved},
        )


# ── Step name sanitization ─────────────────────────────────────────


_SANITIZE_RE = re.compile(r"[^a-z0-9_]")


def sanitize_step_name(raw: str) -> str:
    """Normalize a raw step name into a valid graph node ID.

    - Lowercases
    - Replaces dots, hyphens, spaces, and other non-alphanumeric chars with underscores
    - Strips leading/trailing underscores
    - Collapses multiple consecutive underscores
    - Falls back to "step" if result is empty
    """
    s = raw.lower()
    s = _SANITIZE_RE.sub("_", s)
    s = re.sub(r"_+", "_", s)  # collapse runs
    s = s.strip("_")
    return s or "step"


def _build_name_map(ir: PlanningIR) -> dict[str, str]:
    """Build raw step name → sanitized name mapping, resolving collisions.

    Returns a dict mapping each original step name to its sanitized ID.
    Source references use original names, so the compiler must remap them.
    """
    name_map: dict[str, str] = {}
    used: dict[str, int] = {}  # sanitized → count for collision resolution

    for step in ir.steps:
        sanitized = sanitize_step_name(step.name)
        if sanitized in used:
            used[sanitized] += 1
            sanitized = f"{sanitized}_{used[sanitized]}"
        else:
            used[sanitized] = 1
        name_map[step.name] = sanitized

    return name_map


# ── Compiler ────────────────────────────────────────────────────────


def compile_ir(ir: PlanningIR) -> GlueGraph:
    """Compile a PlanningIR into a GlueGraph.

    Phases:
    0. Sanitize step names (deterministic normalization)
    1. Validate IR consistency (references, effects, cycles)
    2. Generate nodes from steps
    3. Generate edges from sources
    4. Build graph_outputs from final_outputs
    5. Assemble GlueGraph

    Raises CompilerError (or subclass) on any structural problem.
    """
    # Phase 0: build sanitized name map and apply it
    name_map = _build_name_map(ir)
    ir = _apply_name_map(ir, name_map)

    _validate_ir(ir)
    nodes = _build_nodes(ir)
    edges = _build_edges(ir)
    graph_outputs = _build_graph_outputs(ir)
    inputs = [IOField(name=inp.name, type=_normalize_type(inp.type)) for inp in ir.inputs]
    outputs = _build_output_fields(ir)

    graph = GraphBody(
        version=1,
        nodes=nodes,
        edges=edges,
        outputs=graph_outputs,
    )

    return GlueGraph(
        goal=ir.goal,
        inputs=inputs,
        outputs=outputs,
        effects=ir.effects,
        graph=graph,
    )


def _apply_name_map(ir: PlanningIR, name_map: dict[str, str]) -> PlanningIR:
    """Return a new PlanningIR with all step names and references remapped."""
    if all(k == v for k, v in name_map.items()):
        return ir  # nothing to change

    new_steps: list[IRStep] = []
    for step in ir.steps:
        new_sources: dict[str, IRSource] = {}
        for port, src in step.sources.items():
            if src.step == "input":
                new_sources[port] = src
            else:
                new_sources[port] = IRSource(
                    step=name_map.get(src.step, src.step),
                    port=src.port,
                )
        new_steps.append(
            IRStep(
                name=name_map[step.name],
                skill_id=step.skill_id,
                version=step.version,
                sources=new_sources,
                config=step.config,
            )
        )

    new_final_outputs: dict[str, IROutputRef] = {}
    for out_name, ref in ir.final_outputs.items():
        new_final_outputs[out_name] = IROutputRef(
            step=name_map.get(ref.step, ref.step),
            port=ref.port,
        )

    return PlanningIR(
        goal=ir.goal,
        inputs=ir.inputs,
        steps=new_steps,
        final_outputs=new_final_outputs,
        effects=ir.effects,
        reasoning=ir.reasoning,
    )


# ── Internal phases ─────────────────────────────────────────────────


def _validate_ir(ir: PlanningIR) -> None:
    """Validate IR consistency before compilation."""
    if not ir.steps:
        raise EmptyStepsError()

    # Check for duplicate step names
    seen: set[str] = set()
    for step in ir.steps:
        if step.name in seen:
            raise DuplicateStepError(step.name)
        seen.add(step.name)

    input_names = {inp.name for inp in ir.inputs}
    step_names = {s.name for s in ir.steps}

    # Check effects
    for effect in ir.effects:
        if effect not in ALLOWED_EFFECTS:
            raise InvalidEffectError(effect)

    # Check source references
    for step in ir.steps:
        for port, source in step.sources.items():
            if source.step == "input":
                if source.port not in input_names:
                    raise UnknownInputError(step.name, port, source.port)
            elif source.step == step.name:
                raise SelfLoopError(step.name, port)
            elif source.step not in step_names:
                raise UnknownSourceStepError(step.name, port, source.step)

    # Check final_output references
    for out_name, ref in ir.final_outputs.items():
        if ref.step not in step_names:
            raise UnknownOutputStepError(out_name, ref.step)

    # Check for cycles via topological sort
    _check_dag(ir)


def _check_dag(ir: PlanningIR) -> None:
    """Verify the step dependency graph is acyclic (Kahn's algorithm)."""
    step_names = [s.name for s in ir.steps]
    # Build adjacency: step -> set of steps it depends on
    deps: dict[str, set[str]] = {s.name: set() for s in ir.steps}
    for step in ir.steps:
        for source in step.sources.values():
            if source.step != "input":
                deps[step.name].add(source.step)

    # Kahn's
    in_degree = {name: len(d) for name, d in deps.items()}
    queue = [name for name, deg in in_degree.items() if deg == 0]
    visited: list[str] = []

    while queue:
        node = queue.pop(0)
        visited.append(node)
        for name, d in deps.items():
            if node in d:
                in_degree[name] -= 1
                if in_degree[name] == 0:
                    queue.append(name)

    if len(visited) != len(step_names):
        remaining = [n for n in step_names if n not in visited]
        raise CycleError(remaining)


def _normalize_type(type_str: str) -> str:
    """Normalize an IR-declared type to a valid Graphsmith type.

    If the type is not in ALLOWED_TYPES (e.g. 'json', 'text'), fall back
    to 'string'. Also handles parameterized types like 'array<string>'.
    """
    base = type_str.split("<")[0].strip().lower()
    if base in ALLOWED_TYPES or base in ("array", "optional"):
        return type_str
    return "string"


def _normalize_skill_id(skill_id: str, version: str) -> tuple[str, str]:
    """Strip @version suffix from skill_id if present."""
    if "@" in skill_id:
        base, _, ver = skill_id.partition("@")
        return base, ver or version
    return skill_id, version


def _build_nodes(ir: PlanningIR) -> list[GraphNode]:
    """Generate GraphNodes from IR steps."""
    nodes: list[GraphNode] = []
    for step in ir.steps:
        config: dict[str, Any] = {}
        skill_id, version = _normalize_skill_id(step.skill_id, step.version)

        if skill_id in PRIMITIVE_OPS:
            # Primitive op: skill_id IS the op, merge config directly
            op = skill_id
            config = dict(step.config)
        else:
            # Skill invocation
            op = "skill.invoke"
            config = {
                "skill_id": skill_id,
                "version": version,
                **step.config,
            }

        nodes.append(GraphNode(id=step.name, op=op, config=config))
    return nodes


def _build_edges(ir: PlanningIR) -> list[GraphEdge]:
    """Generate GraphEdges from IR step sources."""
    edges: list[GraphEdge] = []
    for step in ir.steps:
        for port, source in step.sources.items():
            if source.step == "input":
                from_addr = f"input.{source.port}"
            else:
                from_addr = f"{source.step}.{source.port}"
            to_addr = f"{step.name}.{port}"
            edges.append(GraphEdge(from_=from_addr, to=to_addr))
    return edges


def _build_graph_outputs(ir: PlanningIR) -> dict[str, str]:
    """Generate graph_outputs mapping from IR final_outputs."""
    return {
        name: f"{ref.step}.{ref.port}"
        for name, ref in ir.final_outputs.items()
    }


def _build_output_fields(ir: PlanningIR) -> list[IOField]:
    """Generate output IOFields from IR final_outputs.

    Uses 'string' as default type since the IR doesn't carry output types.
    The downstream validator will catch type mismatches.
    """
    return [IOField(name=name, type="string") for name in ir.final_outputs]
