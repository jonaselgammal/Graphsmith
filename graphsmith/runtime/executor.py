"""Graph executor — runs validated skill packages deterministically."""
from __future__ import annotations

from typing import Any

from graphsmith.exceptions import ExecutionError, OpError, RegistryError
from graphsmith.models import GraphNode, SkillPackage
from graphsmith.ops.llm_provider import LLMProvider, StubLLMProvider
from graphsmith.ops.registry import execute_op
from graphsmith.runtime.context import ValueStore
from graphsmith.runtime.planner import topological_order
from graphsmith.traces.models import NodeTrace, RunTrace, _now_iso


# ── public API ───────────────────────────────────────────────────────


def run_skill_package(
    pkg: SkillPackage,
    inputs: dict[str, Any],
    *,
    llm_provider: LLMProvider | None = None,
    registry: Any | None = None,
    _depth: int = 0,
    _call_stack: list[tuple[str, str]] | None = None,
) -> ExecutionResult:
    """Execute a validated skill package and return results + trace."""
    provider = llm_provider or StubLLMProvider()
    call_stack = _call_stack or []
    run_trace = RunTrace(
        skill_id=pkg.skill.id,
        started_at=_now_iso(),
        inputs_summary=_summarise(inputs),
    )

    store = ValueStore()

    # 0. Check that all required graph inputs are provided
    _check_required_inputs_provided(pkg, inputs)

    # 1. Seed graph inputs
    for key, value in inputs.items():
        store.put(f"input.{key}", value)

    # 2. Build per-node binding maps (edges + node.inputs merged)
    node_map = {node.id: node for node in pkg.graph.nodes}
    bindings = _build_bindings(pkg, node_map)

    # Identify optional graph inputs (for graceful skip during resolution)
    optional_inputs = {
        f.name for f in pkg.skill.inputs if not f.required
    }
    skipped_nodes: set[str] = set()

    # 3. Topological execution
    order = topological_order(pkg)

    try:
        for node_id in order:
            node = node_map[node_id]
            should_run, skip_reason = _should_run_node(node, store)
            if not should_run:
                now = _now_iso()
                skipped_nodes.add(node.id)
                run_trace.nodes.append(NodeTrace(
                    node_id=node.id,
                    op=node.op,
                    status="skipped",
                    started_at=now,
                    ended_at=now,
                    error=skip_reason,
                ))
                continue
            _execute_node(
                node, bindings[node_id], store, provider,
                run_trace, registry, _depth, call_stack,
                optional_inputs=optional_inputs,
                skipped_nodes=skipped_nodes,
            )
    except (ExecutionError, OpError, RegistryError, NotImplementedError) as exc:
        run_trace.status = "error"
        run_trace.error = str(exc)
        run_trace.ended_at = _now_iso()
        raise ExecutionError(
            f"Execution failed at node '{node_id}': {exc}"
        ) from exc

    # 4. Resolve graph outputs
    graph_outputs: dict[str, Any] = {}
    for output_name, address in pkg.graph.outputs.items():
        graph_outputs[output_name] = store.get(address)

    run_trace.status = "ok"
    run_trace.ended_at = _now_iso()
    run_trace.outputs_summary = _summarise(graph_outputs)

    return ExecutionResult(outputs=graph_outputs, trace=run_trace)


class ExecutionResult:
    """Container for execution outputs and trace."""

    __slots__ = ("outputs", "trace", "repairs")

    def __init__(self, outputs: dict[str, Any], trace: RunTrace) -> None:
        self.outputs = outputs
        self.trace = trace
        self.repairs: list[str] = []


# ── internals ────────────────────────────────────────────────────────


def _build_bindings(
    pkg: SkillPackage,
    node_map: dict[str, GraphNode],
) -> dict[str, dict[str, str]]:
    """Merge edges and node.inputs into per-node port→address maps.

    Raises ExecutionError on conflicting bindings.
    """
    bindings: dict[str, dict[str, str]] = {nid: {} for nid in node_map}

    # Edges
    for edge in pkg.graph.edges:
        dst_scope, dst_port = edge.to.split(".", 1)
        source_address = edge.from_
        if dst_port in bindings[dst_scope]:
            existing = bindings[dst_scope][dst_port]
            if existing != source_address:
                raise ExecutionError(
                    f"Conflicting bindings for node '{dst_scope}' port '{dst_port}': "
                    f"edge provides '{source_address}' but already bound to '{existing}'"
                )
        bindings[dst_scope][dst_port] = source_address

    # Node-level inputs
    for node in pkg.graph.nodes:
        for port, address in node.inputs.items():
            if port in bindings[node.id]:
                existing = bindings[node.id][port]
                if existing != address:
                    raise ExecutionError(
                        f"Conflicting bindings for node '{node.id}' port '{port}': "
                        f"node.inputs provides '{address}' but edge already bound '{existing}'"
                    )
            bindings[node.id][port] = address

    return bindings


def _execute_node(
    node: GraphNode,
    port_bindings: dict[str, str],
    store: ValueStore,
    provider: LLMProvider,
    run_trace: RunTrace,
    registry: Any | None,
    depth: int,
    call_stack: list[tuple[str, str]],
    *,
    optional_inputs: set[str] | None = None,
    skipped_nodes: set[str] | None = None,
) -> None:
    """Resolve inputs, run op, store outputs, record trace."""
    started = _now_iso()
    _optional = optional_inputs or set()
    _skipped = skipped_nodes or set()

    # Resolve bound addresses to actual values.
    # Bindings sourced from optional graph inputs that were not provided
    # are silently skipped — the port is simply absent from resolved_inputs.
    resolved_inputs: dict[str, Any] = {}
    for port, address in port_bindings.items():
        if store.has(address):
            resolved_inputs[port] = store.get(address)
        elif address.startswith("input.") and address.split(".", 1)[1] in _optional:
            continue  # optional input not provided — skip
        elif address.split(".", 1)[0] in _skipped:
            continue  # upstream node skipped — omit the input port
        else:
            # Force the error for required/non-input addresses
            resolved_inputs[port] = store.get(address)

    child_trace = None
    try:
        result = execute_op(
            node.op,
            node.config,
            resolved_inputs,
            llm_provider=provider,
            registry=registry,
            depth=depth,
            call_stack=call_stack,
        )
        # skill.invoke returns (outputs_dict, child_run_trace)
        if isinstance(result, tuple):
            outputs, child_trace = result
        else:
            outputs = result
    except (OpError, ExecutionError, RegistryError, NotImplementedError) as exc:
        run_trace.nodes.append(NodeTrace(
            node_id=node.id,
            op=node.op,
            status="error",
            started_at=started,
            ended_at=_now_iso(),
            inputs_summary=_summarise(resolved_inputs),
            error=str(exc),
        ))
        raise

    # Store outputs
    for port, value in outputs.items():
        store.put(f"{node.id}.{port}", value)

    run_trace.nodes.append(NodeTrace(
        node_id=node.id,
        op=node.op,
        status="ok",
        started_at=started,
        ended_at=_now_iso(),
        inputs_summary=_summarise(resolved_inputs),
        outputs_summary=_summarise(outputs),
        child_trace=child_trace,
    ))


def _check_required_inputs_provided(pkg: SkillPackage, inputs: dict[str, Any]) -> None:
    """Fail early if required graph inputs are missing from user-provided inputs."""
    required = {f.name for f in pkg.skill.inputs if f.required}
    provided = set(inputs.keys())
    missing = required - provided
    if missing:
        raise ExecutionError(
            f"Required input(s) not provided: {', '.join(sorted(missing))}. "
            f"The graph declares these as required inputs but they were not "
            f"included in the input payload. Provided: {sorted(provided)}"
        )


def _should_run_node(node: GraphNode, store: ValueStore) -> tuple[bool, str | None]:
    """Evaluate node.when against the current store."""
    if not node.when:
        return True, None

    negated = node.when.startswith("!")
    address = node.when[1:] if negated else node.when
    if not store.has(address):
        return False, f"Condition '{node.when}' not available"

    value = store.get(address)
    active = not bool(value) if negated else bool(value)
    if active:
        return True, None
    return False, f"Condition '{node.when}' evaluated false"


def _summarise(data: dict[str, Any], max_str_len: int = 200) -> dict[str, Any]:
    """Create a summary-safe copy of a dict (truncate long strings)."""
    out: dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, str) and len(v) > max_str_len:
            out[k] = v[:max_str_len] + "..."
        else:
            out[k] = v
    return out
