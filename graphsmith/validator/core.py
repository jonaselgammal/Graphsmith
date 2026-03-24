"""Deterministic validation for skill packages."""
from __future__ import annotations

from collections import defaultdict

from graphsmith.constants import ALLOWED_EFFECTS, PRIMITIVE_OPS
from graphsmith.exceptions import ValidationError
from graphsmith.models import SkillPackage
from graphsmith.type_system import validate_type_spec


def _split_address(address: str) -> tuple[str, str]:
    """Split an address into scope and port.

    Raises:
        ValidationError: If the address is malformed.
    """
    if "." not in address:
        raise ValidationError(
            f"Invalid address '{address}'. Expected '<scope>.<port>'."
        )
    return address.split(".", 1)


def _split_condition_address(condition: str) -> tuple[bool, str, str]:
    """Split a node condition into (negated, scope, port)."""
    raw = condition[1:] if condition.startswith("!") else condition
    scope, port = _split_address(raw)
    return condition.startswith("!"), scope, port


def validate_skill_package(pkg: SkillPackage) -> list[str]:
    """Validate a parsed skill package.

    Returns a list of warnings (non-fatal). Raises ValidationError on
    any fatal check failure. Checks run in a deterministic order so
    that the first error is always the same for the same input.
    """
    warnings: list[str] = []
    _validate_effects(pkg)
    _validate_types(pkg)
    _validate_node_ids(pkg)
    _validate_ops(pkg)
    _validate_edges(pkg)
    _validate_when_conditions(pkg)
    _validate_binding_conflicts(pkg)
    _validate_required_inputs(pkg)
    _validate_outputs(pkg)
    _validate_dag(pkg)
    return warnings


# ── individual checks ────────────────────────────────────────────────


def _validate_effects(pkg: SkillPackage) -> None:
    invalid = [e for e in pkg.skill.effects if e not in ALLOWED_EFFECTS]
    if invalid:
        raise ValidationError(
            f"Unknown effect(s): {', '.join(sorted(invalid))}. "
            f"Allowed: {', '.join(sorted(ALLOWED_EFFECTS))}"
        )


def _validate_types(pkg: SkillPackage) -> None:
    """Validate that declared input/output types use the allowed vocabulary."""
    for field in [*pkg.skill.inputs, *pkg.skill.outputs]:
        _check_type_string(field.type, context=f"field '{field.name}'")


_PLACEHOLDER_TOKENS = {
    "TYPE", "NAME", "NODE_ID", "OP_NAME", "PORT", "OUTPUT_NAME",
    "STR", "STRING_TYPE",
}


def _check_type_string(type_val: str, *, context: str) -> None:
    """Validate a single type string against the spec grammar."""
    if isinstance(type_val, str):
        # Detect placeholder tokens copied from prompt templates
        if type_val.upper() in _PLACEHOLDER_TOKENS or type_val in _PLACEHOLDER_TOKENS:
            raise ValidationError(
                f"Type '{type_val}' in {context} looks like a placeholder token. "
                "Use a real type: string, integer, number, boolean, bytes, object, "
                "array<string>, optional<string>, union<string, integer>, record<string>, "
                "or ref<SchemaName>."
            )
    validate_type_spec(type_val, context=context)


def _validate_node_ids(pkg: SkillPackage) -> None:
    ids = [node.id for node in pkg.graph.nodes]
    duplicates = {x for x in ids if ids.count(x) > 1}
    if duplicates:
        raise ValidationError(
            f"Duplicate node IDs: {', '.join(sorted(duplicates))}"
        )

    reserved = {"input", "output"}
    bad = [nid for nid in ids if nid in reserved]
    if bad:
        raise ValidationError(
            f"Reserved node ID(s) used: {', '.join(sorted(bad))}. "
            "'input' and 'output' are reserved scopes."
        )


def _validate_ops(pkg: SkillPackage) -> None:
    for node in pkg.graph.nodes:
        if node.op not in PRIMITIVE_OPS:
            raise ValidationError(
                f"Unknown op '{node.op}' on node '{node.id}'. "
                f"Allowed: {', '.join(sorted(PRIMITIVE_OPS))}"
            )


def _validate_edges(pkg: SkillPackage) -> None:
    node_ids = {node.id for node in pkg.graph.nodes}
    input_names = {field.name for field in pkg.skill.inputs}

    for edge in pkg.graph.edges:
        src_scope, src_port = _split_address(edge.from_)
        dst_scope, _ = _split_address(edge.to)

        # source must be 'input' or a known node
        if src_scope != "input" and src_scope not in node_ids:
            raise ValidationError(
                f"Edge source '{edge.from_}' references unknown node '{src_scope}'"
            )
        # destination must be a known node
        if dst_scope not in node_ids:
            raise ValidationError(
                f"Edge destination '{edge.to}' references unknown node '{dst_scope}'"
            )
        # if source is 'input', port must be a declared input
        if src_scope == "input" and src_port not in input_names:
            raise ValidationError(
                f"Edge source '{edge.from_}' references undeclared input '{src_port}'. "
                f"Declared inputs: {', '.join(sorted(input_names))}"
            )


def _validate_binding_conflicts(pkg: SkillPackage) -> None:
    """Check that no destination port receives edges from multiple different sources."""
    # Collect all bindings: edges + node.inputs
    bindings: dict[str, str] = {}  # "node.port" -> source_address

    for edge in pkg.graph.edges:
        dst = edge.to
        src = edge.from_
        if dst in bindings and bindings[dst] != src:
            raise ValidationError(
                f"Conflicting edges: port '{dst}' is targeted by multiple "
                f"sources: '{bindings[dst]}' and '{src}'. "
                "Each destination port can only receive from one source."
            )
        bindings[dst] = src

    for node in pkg.graph.nodes:
        for port, address in node.inputs.items():
            key = f"{node.id}.{port}"
            if key in bindings and bindings[key] != address:
                raise ValidationError(
                    f"Conflicting bindings for port '{key}': "
                    f"edge provides '{bindings[key]}' but node.inputs "
                    f"provides '{address}'. Each port can only have one source."
                )
            bindings[key] = address


def _validate_when_conditions(pkg: SkillPackage) -> None:
    node_ids = {node.id for node in pkg.graph.nodes}
    input_names = {field.name for field in pkg.skill.inputs}

    for node in pkg.graph.nodes:
        if node.when is None:
            continue
        _negated, scope, port = _split_condition_address(node.when)
        if scope == "input":
            if port not in input_names:
                raise ValidationError(
                    f"Node '{node.id}' when-condition references undeclared input '{port}'. "
                    f"Declared inputs: {', '.join(sorted(input_names))}"
                )
        elif scope not in node_ids:
            raise ValidationError(
                f"Node '{node.id}' when-condition references unknown node '{scope}'"
            )


def _validate_required_inputs(pkg: SkillPackage) -> None:
    """Check that every required skill input is wired to at least one edge."""
    required_inputs = {f.name for f in pkg.skill.inputs if f.required}
    wired: set[str] = set()
    for edge in pkg.graph.edges:
        src_scope, src_port = _split_address(edge.from_)
        if src_scope == "input":
            wired.add(src_port)
    for node in pkg.graph.nodes:
        if node.when is None:
            continue
        _negated, scope, port = _split_condition_address(node.when)
        if scope == "input":
            wired.add(port)
    missing = required_inputs - wired
    if missing:
        raise ValidationError(
            f"Required input(s) not wired by any edge or condition: {', '.join(sorted(missing))}"
        )


def _validate_outputs(pkg: SkillPackage) -> None:
    node_ids = {node.id for node in pkg.graph.nodes}
    output_names = {field.name for field in pkg.skill.outputs}

    for output_name, address in pkg.graph.outputs.items():
        if output_name not in output_names:
            raise ValidationError(
                f"Graph output '{output_name}' is not declared in skill.yaml outputs"
            )
        scope, _ = _split_address(address)
        if scope not in node_ids:
            raise ValidationError(
                f"Output '{output_name}' maps to unknown node '{scope}'"
            )

    missing = output_names - set(pkg.graph.outputs.keys())
    if missing:
        raise ValidationError(
            f"Declared output(s) missing from graph_outputs: {', '.join(sorted(missing))}. "
            'Every output in "outputs" must have a matching entry in "graph_outputs" '
            "mapping it to a node port (e.g. \"node_id.port_name\")."
        )


def _validate_dag(pkg: SkillPackage) -> None:
    """Kahn's algorithm — ensures the graph is a DAG."""
    node_ids = {node.id for node in pkg.graph.nodes}
    adj: dict[str, set[str]] = defaultdict(set)
    indegree: dict[str, int] = {nid: 0 for nid in node_ids}

    for edge in pkg.graph.edges:
        src_scope, _ = _split_address(edge.from_)
        dst_scope, _ = _split_address(edge.to)
        if src_scope == "input":
            continue
        if dst_scope not in adj[src_scope]:
            adj[src_scope].add(dst_scope)
            indegree[dst_scope] += 1

    for node in pkg.graph.nodes:
        if node.when is None:
            continue
        _negated, src_scope, _ = _split_condition_address(node.when)
        if src_scope == "input":
            continue
        if node.id not in adj[src_scope]:
            adj[src_scope].add(node.id)
            indegree[node.id] += 1

    queue = sorted(nid for nid, deg in indegree.items() if deg == 0)
    visited = 0

    while queue:
        current = queue.pop(0)
        visited += 1
        for nxt in sorted(adj[current]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if visited != len(node_ids):
        raise ValidationError(
            "Graph contains a cycle. All graphs must be DAGs in v1."
        )
