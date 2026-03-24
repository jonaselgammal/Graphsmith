"""Deterministic graph-level repair informed by runtime failures."""
from __future__ import annotations

import re

from graphsmith.constants import PRIMITIVE_OPS
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.planner.models import GlueGraph

_GENERIC_COLLECTION_OUTPUTS = {"result", "results", "mapped"}
_PRIMITIVE_OUTPUT_PORTS = {
    "template.render": "rendered",
    "json.parse": "parsed",
    "select.fields": "selected",
    "assert.check": "value",
    "branch.if": "result",
    "fallback.try": "result",
    "llm.generate": "text",
    "llm.extract": "extracted",
    "array.map": "mapped",
    "array.filter": "filtered",
    "parallel.map": "results",
    "text.normalize": "normalized",
    "text.word_count": "count",
    "text.reverse": "reversed",
    "text.sort_lines": "sorted",
    "text.remove_duplicates": "deduplicated",
    "text.title_case": "titled",
}


def normalize_glue_graph_contracts(glue: GlueGraph) -> tuple[GlueGraph, list[str]]:
    """Normalize common legacy graph contracts before validation/execution."""
    repaired = glue
    actions: list[str] = []

    for node in list(repaired.graph.nodes):
        if node.op in {"array.map", "parallel.map"}:
            has_array_binding = "array" in node.inputs or any(
                edge.to == f"{node.id}.array" for edge in repaired.graph.edges
            )
            if has_array_binding:
                repaired = _rewrite_node_input_alias(repaired, node.id, "array", "items")
                actions.append(
                    f"graph:{node.id}: rewrite {node.op} input references from array to items"
                )
                node = next(n for n in repaired.graph.nodes if n.id == node.id)

        if node.op != "parallel.map":
            continue

        node_actions: list[str] = []
        config = dict(node.config)
        operation = config.pop("operation", None)
        if operation and "op" not in config:
            if isinstance(operation, str):
                _lift_parallel_map_operation(config, operation)
                node_actions.append(
                    f"graph:{node.id}: lift parallel.map operation '{operation}' into runtime config"
                )
            elif isinstance(operation, dict):
                nested_actions = _lift_parallel_map_operation_object(node.id, config, operation)
                node_actions.extend(nested_actions)

        if config.get("op") == "skill.invoke":
            flattened, flatten_actions = _flatten_parallel_map_skill_invoke(node.id, config)
            config = flattened
            node_actions.extend(flatten_actions)

        input_port = config.get("input_port")
        if isinstance(input_port, str) and input_port and "item_input" not in config:
            config["item_input"] = input_port
            node_actions.append(
                f"graph:{node.id}: rewrite parallel.map input_port '{input_port}' to item_input"
            )

        output_port = config.get("output_port")
        if isinstance(output_port, str) and output_port and output_port != "results":
            if not config.get("aggregate_outputs"):
                config["aggregate_outputs"] = True
                node_actions.append(
                    f"graph:{node.id}: enable aggregated outputs for parallel.map output_port '{output_port}'"
                )

        referenced_ports = _collect_referenced_ports(repaired, node.id)
        if "mapped" in referenced_ports:
            repaired = _rewrite_node_port_alias(repaired, node.id, "mapped", "results")
            node_actions.append(
                f"graph:{node.id}: rewrite mapped output references to results"
            )
            referenced_ports.discard("mapped")
            referenced_ports.add("results")

        if any(port != "results" for port in referenced_ports):
            if not config.get("aggregate_outputs"):
                config["aggregate_outputs"] = True
                node_actions.append(
                    f"graph:{node.id}: enable aggregated named outputs for parallel.map"
                )

        if config != node.config:
            repaired = _update_node_config(repaired, node.id, config)

        actions.extend(node_actions)

    repaired, output_actions = _align_glue_output_contracts(repaired)
    actions.extend(output_actions)

    return repaired, actions


def repair_glue_graph_from_runtime_error(
    glue: GlueGraph,
    error_text: str,
) -> tuple[GlueGraph, list[str]]:
    """Attempt one bounded graph repair from a runtime error message."""
    repaired = glue
    actions: list[str] = []

    alias_match = re.search(
        r"Address '([A-Za-z0-9_]+)\.mapped' has no value\..*'([A-Za-z0-9_]+)\.results'",
        error_text,
    )
    if alias_match and alias_match.group(1) == alias_match.group(2):
        node_id = alias_match.group(1)
        repaired = _rewrite_node_port_alias(repaired, node_id, "mapped", "results")
        actions.append(f"runtime:{node_id}: rewrite mapped output references to results")

    result_alias_match = re.search(
        r"Address '([A-Za-z0-9_]+)\.result' has no value\..*'([A-Za-z0-9_]+)\.results'",
        error_text,
    )
    if result_alias_match and result_alias_match.group(1) == result_alias_match.group(2):
        node_id = result_alias_match.group(1)
        repaired = _rewrite_node_port_alias(repaired, node_id, "result", "results")
        actions.append(f"runtime:{node_id}: rewrite result output references to results")

    items_match = re.search(
        r"Execution failed at node '([A-Za-z0-9_]+)': array\.map requires input 'items'",
        error_text,
    )
    if items_match:
        node_id = items_match.group(1)
        repaired = _rewrite_node_input_alias(repaired, node_id, "array", "items")
        actions.append(f"runtime:{node_id}: rewrite array.map input references from array to items")

    parallel_items_match = re.search(
        r"Execution failed at node '([A-Za-z0-9_]+)': parallel\.map requires input 'items'",
        error_text,
    )
    if parallel_items_match:
        node_id = parallel_items_match.group(1)
        repaired = _rewrite_node_input_alias(repaired, node_id, "array", "items")
        actions.append(
            f"runtime:{node_id}: rewrite parallel.map input references from array to items"
        )

    return repaired, actions


def _rewrite_node_port_alias(
    glue: GlueGraph,
    node_id: str,
    old_port: str,
    new_port: str,
) -> GlueGraph:
    old_addr = f"{node_id}.{old_port}"
    new_addr = f"{node_id}.{new_port}"

    new_nodes = [
        node.model_copy(
            update={
                "inputs": {
                    port: (new_addr if address == old_addr else address)
                    for port, address in node.inputs.items()
                }
            }
        )
        for node in glue.graph.nodes
    ]
    new_edges = [
        edge.model_copy(update={"from_": new_addr}) if edge.from_ == old_addr else edge
        for edge in glue.graph.edges
    ]
    new_outputs = {
        name: (new_addr if address == old_addr else address)
        for name, address in glue.graph.outputs.items()
    }

    return glue.model_copy(
        update={
            "graph": GraphBody(
                version=glue.graph.version,
                nodes=new_nodes,
                edges=new_edges,
                outputs=new_outputs,
            )
        }
    )


def _update_node_config(
    glue: GlueGraph,
    node_id: str,
    config: dict[str, object],
) -> GlueGraph:
    new_nodes = [
        node.model_copy(update={"config": config}) if node.id == node_id else node
        for node in glue.graph.nodes
    ]
    return glue.model_copy(
        update={
            "graph": GraphBody(
                version=glue.graph.version,
                nodes=new_nodes,
                edges=list(glue.graph.edges),
                outputs=dict(glue.graph.outputs),
            )
        }
    )


def _rewrite_node_input_alias(
    glue: GlueGraph,
    node_id: str,
    old_port: str,
    new_port: str,
) -> GlueGraph:
    old_to = f"{node_id}.{old_port}"
    new_to = f"{node_id}.{new_port}"

    new_nodes: list[GraphNode] = []
    for node in glue.graph.nodes:
        if node.id != node_id:
            new_nodes.append(node)
            continue
        new_inputs = dict(node.inputs)
        if old_port in new_inputs and new_port not in new_inputs:
            new_inputs[new_port] = new_inputs.pop(old_port)
        new_nodes.append(node.model_copy(update={"inputs": new_inputs}))

    new_edges: list[GraphEdge] = []
    for edge in glue.graph.edges:
        if edge.to == old_to:
            new_edges.append(edge.model_copy(update={"to": new_to}))
        else:
            new_edges.append(edge)

    return glue.model_copy(
        update={
            "graph": GraphBody(
                version=glue.graph.version,
                nodes=new_nodes,
                edges=new_edges,
                outputs=dict(glue.graph.outputs),
            )
        }
    )


def _collect_referenced_ports(glue: GlueGraph, node_id: str) -> set[str]:
    prefix = f"{node_id}."
    refs: set[str] = set()
    for edge in glue.graph.edges:
        if edge.from_.startswith(prefix):
            refs.add(edge.from_.split(".", 1)[1])
    for address in glue.graph.outputs.values():
        if address.startswith(prefix):
            refs.add(address.split(".", 1)[1])
    for node in glue.graph.nodes:
        for address in node.inputs.values():
            if address.startswith(prefix):
                refs.add(address.split(".", 1)[1])
    return refs


def _align_glue_output_contracts(glue: GlueGraph) -> tuple[GlueGraph, list[str]]:
    output_name_by_node_port = {
        address: name for name, address in glue.graph.outputs.items()
    }
    repaired = glue
    actions: list[str] = []
    node_map = {node.id: node for node in glue.graph.nodes}

    for output_name, address in list(repaired.graph.outputs.items()):
        if "." not in address:
            continue
        node_id, port = address.split(".", 1)
        node = node_map.get(node_id)
        if node is None or node.op != "parallel.map":
            continue
        if output_name == "result":
            continue
        if output_name not in _GENERIC_COLLECTION_OUTPUTS and port not in _GENERIC_COLLECTION_OUTPUTS:
            continue
        inferred = _infer_parallel_map_named_output(node)
        if not inferred or inferred in _GENERIC_COLLECTION_OUTPUTS:
            continue

        if not node.config.get("aggregate_outputs"):
            updated_config = dict(node.config)
            updated_config["aggregate_outputs"] = True
            repaired = _update_node_config(repaired, node.id, updated_config)
            actions.append(
                f"graph:{node.id}: enable aggregated named outputs for parallel.map"
            )
            node_map = {n.id: n for n in repaired.graph.nodes}
            node = node_map[node_id]

        new_name = inferred if output_name in _GENERIC_COLLECTION_OUTPUTS else output_name
        new_address = f"{node_id}.{inferred}"
        if output_name == new_name and address == new_address:
            continue
        if new_name != output_name and new_name in repaired.graph.outputs:
            continue

        repaired = _rewrite_graph_output(repaired, output_name, new_name, new_address)
        actions.append(
            f"graph:{node_id}: align generic output '{output_name}' to named output '{new_name}'"
        )
        node_map = {n.id: n for n in repaired.graph.nodes}

    return repaired, actions


def _rewrite_graph_output(
    glue: GlueGraph,
    old_name: str,
    new_name: str,
    new_address: str,
) -> GlueGraph:
    new_outputs: dict[str, str] = {}
    for name, address in glue.graph.outputs.items():
        if name == old_name:
            new_outputs[new_name] = new_address
        else:
            new_outputs[name] = address

    output_fields: list[IOField] = []
    for field in glue.outputs:
        if field.name == old_name:
            output_fields.append(field.model_copy(update={"name": new_name}))
        else:
            output_fields.append(field)

    return glue.model_copy(
        update={
            "outputs": output_fields,
            "graph": GraphBody(
                version=glue.graph.version,
                nodes=list(glue.graph.nodes),
                edges=list(glue.graph.edges),
                outputs=new_outputs,
            ),
        }
    )


def _infer_parallel_map_named_output(node: GraphNode) -> str | None:
    config = node.config
    output_port = config.get("output_port")
    if isinstance(output_port, str) and output_port and output_port not in _GENERIC_COLLECTION_OUTPUTS:
        return output_port

    op = config.get("op")
    if isinstance(op, str) and op in _PRIMITIVE_OUTPUT_PORTS:
        return _PRIMITIVE_OUTPUT_PORTS[op]

    if op == "skill.invoke":
        op_config = config.get("op_config")
        if isinstance(op_config, dict):
            output_mapping = op_config.get("output_mapping")
            if isinstance(output_mapping, dict) and len(output_mapping) == 1:
                mapped_name = next(iter(output_mapping))
                if isinstance(mapped_name, str) and mapped_name:
                    return mapped_name

    if op == "__inline_graph__":
        body = config.get("body")
        if isinstance(body, dict):
            outputs = body.get("outputs")
            if isinstance(outputs, list) and len(outputs) == 1:
                first = outputs[0]
                if isinstance(first, dict):
                    name = first.get("name")
                    if isinstance(name, str) and name:
                        return name

    return None


def _lift_parallel_map_operation(config: dict[str, object], operation: str) -> None:
    if operation in PRIMITIVE_OPS:
        config["op"] = operation
        if operation.startswith("text.") and "item_input" not in config:
            config["item_input"] = "text"
        elif operation.startswith("json.") and "item_input" not in config:
            config["item_input"] = "raw_json"
        return

    skill_id = operation if ".v" in operation else f"{operation}.v1"
    config["op"] = "skill.invoke"
    config["op_config"] = {
        "skill_id": skill_id,
        "version": "1.0.0",
    }
    config.setdefault("item_input", "text")


def _flatten_parallel_map_skill_invoke(
    node_id: str,
    config: dict[str, object],
) -> tuple[dict[str, object], list[str]]:
    op_config = config.get("op_config")
    if not isinstance(op_config, dict):
        return config, []

    nested = op_config.get("skill_id")
    if not isinstance(nested, dict):
        return config, []

    nested_skill_id = nested.get("skill_id")
    nested_version = nested.get("version") or op_config.get("version")
    if not isinstance(nested_skill_id, str) or not isinstance(nested_version, str):
        return config, []

    new_config = dict(config)
    new_config["op_config"] = {
        "skill_id": nested_skill_id,
        "version": nested_version,
    }
    actions = [
        f"graph:{node_id}: flatten nested parallel.map skill.invoke target '{nested_skill_id}'"
    ]

    input_mapping = nested.get("input_mapping")
    if (
        isinstance(input_mapping, dict)
        and len(input_mapping) == 1
        and "item" in input_mapping.values()
    ):
        new_config["item_input"] = next(iter(input_mapping))
        actions.append(
            f"graph:{node_id}: derive parallel.map item_input '{new_config['item_input']}' from skill mapping"
        )

    output_mapping = nested.get("output_mapping")
    if isinstance(output_mapping, dict) and output_mapping:
        new_config["aggregate_outputs"] = True
        actions.append(
            f"graph:{node_id}: enable aggregated outputs from nested skill output mapping"
        )

    return new_config, actions


def _lift_parallel_map_operation_object(
    node_id: str,
    config: dict[str, object],
    operation: dict[str, object],
) -> list[str]:
    skill_id = operation.get("skill_id")
    version = operation.get("version", "1.0.0")
    if not isinstance(skill_id, str) or not isinstance(version, str):
        return []

    config["op"] = "skill.invoke"
    config["op_config"] = {
        "skill_id": skill_id,
        "version": version,
    }
    actions = [
        f"graph:{node_id}: lift structured parallel.map operation '{skill_id}' into runtime config"
    ]

    input_mapping = operation.get("input_mapping")
    if (
        isinstance(input_mapping, dict)
        and len(input_mapping) == 1
        and "item" in input_mapping.values()
    ):
        config["item_input"] = next(iter(input_mapping))
        actions.append(
            f"graph:{node_id}: derive parallel.map item_input '{config['item_input']}' from structured operation"
        )

    output_mapping = operation.get("output_mapping")
    if isinstance(output_mapping, dict) and output_mapping:
        config["aggregate_outputs"] = True
        actions.append(
            f"graph:{node_id}: enable aggregated outputs from structured operation mapping"
        )

    return actions
