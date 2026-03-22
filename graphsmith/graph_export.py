"""Graph export — convert compiled graphs to DOT and structured JSON."""
from __future__ import annotations

import json
from typing import Any

from graphsmith.planner.models import GlueGraph


def graph_to_dot(glue: GlueGraph) -> str:
    """Export a GlueGraph as Graphviz DOT format."""
    lines = ['digraph G {', '  rankdir=TB;', '  node [shape=box, style=rounded];', '']

    # Input node
    lines.append('  subgraph cluster_inputs {')
    lines.append('    label="Inputs"; style=dashed; color=gray;')
    for inp in glue.inputs:
        lines.append(f'    "input.{inp.name}" [label="{inp.name}\\n({inp.type})", shape=ellipse, style=filled, fillcolor="#e8f4f8"];')
    lines.append('  }')
    lines.append('')

    # Skill nodes
    for node in glue.graph.nodes:
        skill = node.config.get("skill_id", node.op)
        label = f"{node.id}\\n{skill}"
        lines.append(f'  "{node.id}" [label="{label}"];')
    lines.append('')

    # Edges
    for edge in glue.graph.edges:
        src = edge.from_.split(".")[0]
        dst = edge.to.split(".")[0]
        port_label = edge.to.split(".", 1)[1] if "." in edge.to else ""
        lines.append(f'  "{src}" -> "{dst}" [label="{port_label}", fontsize=9];')
    lines.append('')

    # Output node
    lines.append('  subgraph cluster_outputs {')
    lines.append('    label="Outputs"; style=dashed; color=gray;')
    for name, addr in glue.graph.outputs.items():
        lines.append(f'    "output.{name}" [label="{name}", shape=ellipse, style=filled, fillcolor="#d4edda"];')
    lines.append('  }')
    for name, addr in glue.graph.outputs.items():
        src = addr.split(".")[0]
        lines.append(f'  "{src}" -> "output.{name}" [style=dashed];')

    lines.append('}')
    return "\n".join(lines)


def graph_to_json(glue: GlueGraph) -> dict[str, Any]:
    """Export a GlueGraph as structured JSON."""
    nodes = []
    for node in glue.graph.nodes:
        nodes.append({
            "id": node.id,
            "op": node.op,
            "skill_id": node.config.get("skill_id", ""),
            "config": {k: v for k, v in node.config.items() if k not in ("skill_id", "version")},
        })

    edges = [{"from": e.from_, "to": e.to} for e in glue.graph.edges]

    return {
        "goal": glue.goal,
        "inputs": [{"name": i.name, "type": i.type} for i in glue.inputs],
        "outputs": dict(glue.graph.outputs),
        "nodes": nodes,
        "edges": edges,
        "effects": glue.effects,
    }


def graph_to_ascii(glue: GlueGraph) -> str:
    """Render a compact ASCII representation of the graph."""
    lines: list[str] = []

    # Chain representation
    node_names = [n.id for n in glue.graph.nodes]
    chain = " \u2192 ".join(node_names)
    lines.append(f"  Flow: {chain}")

    # Input/output summary
    inputs = ", ".join(f"{i.name}" for i in glue.inputs)
    outputs = ", ".join(f"{k}" for k in glue.graph.outputs)
    lines.append(f"  Inputs: {inputs}")
    lines.append(f"  Outputs: {outputs}")

    return "\n".join(lines)
