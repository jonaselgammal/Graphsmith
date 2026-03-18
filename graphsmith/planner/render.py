"""Graph inspection and Mermaid rendering for GlueGraphs and SkillPackages."""
from __future__ import annotations

from typing import Any

from graphsmith.planner.models import GlueGraph


def render_plan_text(glue: GlueGraph) -> str:
    """Render a GlueGraph as human-readable text."""
    lines: list[str] = []
    lines.append(f"Plan: {glue.goal}")
    lines.append(f"Inputs: {', '.join(f.name for f in glue.inputs)}")
    lines.append(f"Outputs: {', '.join(f.name for f in glue.outputs)}")
    if glue.effects:
        lines.append(f"Effects: {', '.join(glue.effects)}")

    lines.append(f"\nNodes ({len(glue.graph.nodes)}):")
    for n in glue.graph.nodes:
        skill = n.config.get("skill_id", "")
        ver = n.config.get("version", "")
        if skill:
            lines.append(f"  {n.id}: {n.op} → {skill}@{ver}")
        else:
            lines.append(f"  {n.id}: {n.op}")

    lines.append(f"\nEdges ({len(glue.graph.edges)}):")
    for e in glue.graph.edges:
        lines.append(f"  {e.from_} → {e.to}")

    lines.append(f"\nGraph outputs:")
    for name, addr in glue.graph.outputs.items():
        lines.append(f"  {name} ← {addr}")

    return "\n".join(lines)


def render_plan_mermaid(glue: GlueGraph) -> str:
    """Render a GlueGraph as a Mermaid flowchart."""
    lines: list[str] = []
    lines.append("```mermaid")
    lines.append("flowchart TD")

    # Input node
    input_names = ", ".join(f.name for f in glue.inputs)
    lines.append(f'    Inputs["Inputs<br/>{input_names}"]')

    # Skill nodes
    for n in glue.graph.nodes:
        skill = n.config.get("skill_id", n.op)
        lines.append(f'    {n.id}["{n.id}<br/>{skill}"]')

    # Output node
    output_names = ", ".join(f.name for f in glue.outputs)
    lines.append(f'    Outputs["Outputs<br/>{output_names}"]')

    lines.append("")

    # Edges
    for e in glue.graph.edges:
        src_scope, src_port = e.from_.split(".", 1)
        dst_scope, dst_port = e.to.split(".", 1)

        if src_scope == "input":
            lines.append(f"    Inputs -->|{src_port}| {dst_scope}")
        else:
            lines.append(f"    {src_scope} -->|{src_port}| {dst_scope}")

    # Output edges
    for name, addr in glue.graph.outputs.items():
        node_scope = addr.split(".", 1)[0]
        lines.append(f"    {node_scope} -->|{name}| Outputs")

    lines.append("```")
    return "\n".join(lines)
