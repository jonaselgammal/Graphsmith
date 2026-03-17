"""Parse raw LLM planner output into typed PlanResult / GlueGraph."""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.planner.models import GlueGraph, PlanResult, UnresolvedHole

_REQUIRED_KEYS = {"inputs", "outputs", "nodes", "edges", "graph_outputs"}


def parse_planner_output(raw: str, *, goal: str) -> PlanResult:
    """Parse raw LLM text into a typed PlanResult.

    Extraction strategy (in order):
    1. Try the raw text as JSON directly
    2. Try extracting a fenced code block
    3. Try extracting the first balanced {…} block from the text

    Returns success/partial/failure with structured error information.
    """
    text = _extract_json_text(raw)

    # Parse JSON
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return PlanResult(
            status="failure",
            holes=[
                UnresolvedHole(
                    node_id="(parser)",
                    kind="validation_error",
                    description=f"Invalid JSON in planner output: {exc}",
                )
            ],
            reasoning=f"Raw output (unparsed): {raw[:500]}",
        )

    if not isinstance(data, dict):
        return PlanResult(
            status="failure",
            holes=[
                UnresolvedHole(
                    node_id="(parser)",
                    kind="validation_error",
                    description=f"Expected JSON object, got {type(data).__name__}",
                )
            ],
            reasoning=f"Raw output: {raw[:500]}",
        )

    # Check required keys
    missing = _REQUIRED_KEYS - set(data.keys())
    if missing:
        return PlanResult(
            status="failure",
            holes=[
                UnresolvedHole(
                    node_id="(parser)",
                    kind="validation_error",
                    description=(
                        f"Missing required keys in planner output: "
                        f"{', '.join(sorted(missing))}"
                    ),
                )
            ],
            reasoning=data.get("reasoning", ""),
        )

    # Build models
    try:
        glue = _build_glue_graph(data, goal=goal)
    except (PydanticValidationError, KeyError, TypeError, ValueError) as exc:
        return PlanResult(
            status="failure",
            holes=[
                UnresolvedHole(
                    node_id="(parser)",
                    kind="validation_error",
                    description=f"Failed to build graph models: {exc}",
                )
            ],
            reasoning=data.get("reasoning", ""),
        )

    # Extract LLM-provided holes
    holes = _extract_holes(data)
    reasoning = data.get("reasoning", "")

    status = "partial" if holes else "success"
    return PlanResult(
        status=status,
        graph=glue,
        holes=holes,
        reasoning=reasoning,
    )


# ── JSON extraction ──────────────────────────────────────────────────


def _extract_json_text(raw: str) -> str:
    """Extract the JSON payload from raw LLM output.

    Tries in order:
    1. Raw text is valid JSON → return as-is
    2. Fenced code block → extract content
    3. First balanced {…} block → extract it
    4. Return stripped text (will fail at json.loads)
    """
    stripped = raw.strip()

    # 1. Fenced code block (```json ... ``` or ``` ... ```)
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", stripped, re.DOTALL)
    if m:
        return m.group(1).strip()

    # 2. First balanced { ... } block in the text
    brace_start = stripped.find("{")
    if brace_start != -1:
        extracted = _extract_balanced_braces(stripped, brace_start)
        if extracted:
            return extracted

    # 3. Fallback — return stripped, will fail at json.loads
    return stripped


def _extract_balanced_braces(text: str, start: int) -> str | None:
    """Extract the first balanced {…} block starting at *start*."""
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


# ── model building ───────────────────────────────────────────────────


def _build_glue_graph(data: dict[str, Any], *, goal: str) -> GlueGraph:
    """Construct a GlueGraph from parsed JSON data."""
    inputs = [
        IOField(
            name=f["name"],
            type=f.get("type", "string"),
            required=f.get("required", True),
        )
        for f in data["inputs"]
    ]
    outputs = [
        IOField(
            name=f["name"],
            type=f.get("type", "string"),
        )
        for f in data["outputs"]
    ]
    nodes = [
        GraphNode(
            id=n["id"],
            op=n["op"],
            config=n.get("config", {}),
            inputs=n.get("inputs", {}),
        )
        for n in data["nodes"]
    ]
    edges = [
        GraphEdge(from_=e["from"], to=e["to"])
        for e in data["edges"]
    ]
    graph = GraphBody(
        version=1,
        nodes=nodes,
        edges=edges,
        outputs=data["graph_outputs"],
    )
    effects = data.get("effects", ["pure"])

    return GlueGraph(
        goal=goal,
        inputs=inputs,
        outputs=outputs,
        effects=effects,
        graph=graph,
    )


def _extract_holes(data: dict[str, Any]) -> list[UnresolvedHole]:
    """Extract unresolved holes from the parsed data, if present."""
    raw_holes = data.get("holes", [])
    holes: list[UnresolvedHole] = []
    for h in raw_holes:
        if not isinstance(h, dict):
            continue
        kind = h.get("kind", "missing_skill")
        valid_kinds = {
            "missing_skill", "ambiguous_candidate",
            "missing_output_path", "unsupported_op", "validation_error",
        }
        if kind not in valid_kinds:
            kind = "missing_skill"
        holes.append(
            UnresolvedHole(
                node_id=h.get("node_id", "(unknown)"),
                kind=kind,  # type: ignore[arg-type]
                description=h.get("description", ""),
                candidates=h.get("candidates", []),
            )
        )
    return holes
