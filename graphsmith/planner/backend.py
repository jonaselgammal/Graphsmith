"""Planner backend interface and mock implementation."""
from __future__ import annotations

from typing import Any, Protocol

from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.planner.models import (
    GlueGraph,
    PlanRequest,
    PlanResult,
    UnresolvedHole,
)


class PlannerBackend(Protocol):
    """Interface for planner backends."""

    def compose(self, request: PlanRequest) -> PlanResult: ...


class MockPlannerBackend:
    """Test backend that builds a plan from candidate skills.

    Strategy: for each candidate, create a skill.invoke node and
    chain them sequentially. This produces a valid (if naive) plan
    for testing the planner pipeline.
    """

    def compose(self, request: PlanRequest) -> PlanResult:
        if not request.candidates:
            return PlanResult(
                status="failure",
                holes=[
                    UnresolvedHole(
                        node_id="(none)",
                        kind="missing_skill",
                        description="No candidate skills available to compose a plan.",
                    )
                ],
                reasoning="No skills found in the registry for this goal.",
                candidates_considered=[],
            )

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []
        graph_inputs: list[IOField] = []
        graph_outputs: list[IOField] = []
        effects: set[str] = set()
        output_map: dict[str, str] = {}
        cand_ids: list[str] = []

        primary = request.candidates[0]
        cand_ids = [f"{c.id}@{c.version}" for c in request.candidates]
        node_id = _safe_node_id(primary.id)

        nodes.append(
            GraphNode(
                id=node_id,
                op="skill.invoke",
                config={"skill_id": primary.id, "version": primary.version},
            )
        )
        for inp_name in primary.input_names:
            graph_inputs.append(IOField(name=inp_name, type="string"))
            edges.append(GraphEdge(from_=f"input.{inp_name}", to=f"{node_id}.{inp_name}"))
        effects.update(primary.effects)

        secondary = _find_chainable_secondary(primary, request.candidates[1:])
        if secondary is None:
            for out_name in primary.output_names:
                graph_outputs.append(IOField(name=out_name, type="string"))
                output_map[out_name] = f"{node_id}.{out_name}"
        else:
            secondary_id = _safe_node_id(secondary.id)
            nodes.append(
                GraphNode(
                    id=secondary_id,
                    op="skill.invoke",
                    config={"skill_id": secondary.id, "version": secondary.version},
                )
            )
            primary_output_names = set(primary.output_names)
            existing_graph_inputs = {field.name for field in graph_inputs}
            for inp_name in secondary.input_names:
                matched_output = _match_primary_output_to_secondary_input(primary_output_names, inp_name)
                if matched_output is not None:
                    edges.append(GraphEdge(from_=f"{node_id}.{matched_output}", to=f"{secondary_id}.{inp_name}"))
                else:
                    if inp_name not in existing_graph_inputs:
                        graph_inputs.append(IOField(name=inp_name, type="string"))
                        existing_graph_inputs.add(inp_name)
                    edges.append(GraphEdge(from_=f"input.{inp_name}", to=f"{secondary_id}.{inp_name}"))

            for out_name in secondary.output_names:
                graph_outputs.append(IOField(name=out_name, type="string"))
                output_map[out_name] = f"{secondary_id}.{out_name}"
            effects.update(secondary.effects)
            cand_ids = [f"{primary.id}@{primary.version}", f"{secondary.id}@{secondary.version}", *cand_ids[2:]]

        # If desired_outputs are specified but not covered, add holes
        holes: list[UnresolvedHole] = []
        if request.desired_outputs:
            covered = {o.name for o in graph_outputs}
            for desired in request.desired_outputs:
                if desired.name not in covered:
                    holes.append(
                        UnresolvedHole(
                            node_id="(output)",
                            kind="missing_output_path",
                            description=(
                                f"Desired output '{desired.name}' is not produced "
                                f"by the composed graph."
                            ),
                        )
                    )

        graph = GlueGraph(
            goal=request.goal,
            inputs=graph_inputs,
            outputs=graph_outputs,
            effects=sorted(effects),
            graph=GraphBody(
                version=1,
                nodes=nodes,
                edges=edges,
                outputs=output_map,
            ),
        )

        status = "partial" if holes else "success"
        return PlanResult(
            status=status,
            graph=graph,
            holes=holes,
            reasoning=(
                f"Mock planner: composed plan using primary skill "
                f"'{primary.id}@{primary.version}'"
                + (
                    f" plus adjacent skill '{secondary.id}@{secondary.version}'."
                    if secondary is not None else "."
                )
            ),
            candidates_considered=cand_ids,
        )


def _find_chainable_secondary(primary: Any, candidates: list[Any]) -> Any | None:
    """Find a simple adjacent skill that can consume the primary output."""
    primary_outputs = set(primary.output_names)
    for cand in candidates:
        matched = False
        for inp_name in cand.input_names:
            if _match_primary_output_to_secondary_input(primary_outputs, inp_name) is not None:
                matched = True
                break
        if matched:
            return cand
    return None


def _match_primary_output_to_secondary_input(
    primary_outputs: set[str],
    secondary_input: str,
) -> str | None:
    if secondary_input in primary_outputs:
        return secondary_input
    alias_sources = {
        "text": ["stdout", "result", "normalized", "summary", "formatted", "prefixed"],
        "lines": ["keywords"],
    }
    for source in alias_sources.get(secondary_input, []):
        if source in primary_outputs:
            return source
    return None


def _safe_node_id(skill_id: str) -> str:
    """Convert a skill ID to a valid node ID (replace dots with underscores)."""
    return skill_id.replace(".", "_")
