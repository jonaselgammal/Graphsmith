"""Build a structured planning prompt for the planner backend.

[graphsmith-planner-prompt v3]
"""
from __future__ import annotations

from graphsmith.constants import PRIMITIVE_OPS
from graphsmith.planner.models import PlanRequest

PROMPT_VERSION = "v3"

_SYSTEM_MESSAGE = (
    "You are a Graphsmith graph planner. "
    "You compose directed acyclic graphs (DAGs) from available skills and primitive ops. "
    "Respond with JSON only. No explanation before or after the JSON."
)

_OUTPUT_CONTRACT = """\
# Required output format

Respond with ONLY a JSON object. No prose, no markdown, no explanation.

Required keys: "inputs", "outputs", "nodes", "edges", "graph_outputs".
Optional keys: "effects", "holes", "reasoning".

Rules:
- Every name in "outputs" MUST have a matching entry in "graph_outputs".
- Only include inputs in "inputs" that the user would provide for this goal.
  Do NOT add optional skill inputs unless the goal explicitly requires them.
- Every edge "from" address of the form "input.X" must have X declared in "inputs".
- "outputs" should list ONLY the final deliverables requested by the goal.
  Do NOT expose intermediate results unless the goal explicitly asks for them.
- Name each output using the output port name of the skill that produces it
  (e.g. if text.summarize.v1 outputs "summary", name the graph output "summary").
  This ensures graph_outputs can map directly: {"summary": "summarize_node.summary"}.

Use real names and types derived from the goal and available skills.
Never output placeholder tokens or template variables.

## Allowed types
string, integer, number, boolean, bytes, object,
array<string>, array<integer>, array<object>,
optional<string>, optional<integer>

## Example 1: single-skill plan (text input only)

```json
{
  "inputs": [{"name": "text", "type": "string"}],
  "outputs": [{"name": "summary", "type": "string"}],
  "nodes": [
    {"id": "call", "op": "skill.invoke", "config": {"skill_id": "text.summarize.v1", "version": "1.0.0"}}
  ],
  "edges": [
    {"from": "input.text", "to": "call.text"}
  ],
  "graph_outputs": {"summary": "call.summary"},
  "effects": ["llm_inference"]
}
```

## Example 2: multi-skill chain (only final output exposed)

Goal: "Normalize text and then summarize it"
Note: "normalized" is an intermediate result, NOT a final output.
Only "summary" is the deliverable the user asked for.

```json
{
  "inputs": [{"name": "text", "type": "string"}],
  "outputs": [{"name": "summary", "type": "string"}],
  "nodes": [
    {"id": "normalize", "op": "skill.invoke", "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
    {"id": "summarize", "op": "skill.invoke", "config": {"skill_id": "text.summarize.v1", "version": "1.0.0"}}
  ],
  "edges": [
    {"from": "input.text", "to": "normalize.text"},
    {"from": "normalize.normalized", "to": "summarize.text"}
  ],
  "graph_outputs": {"summary": "summarize.summary"},
  "effects": ["llm_inference"]
}
```

## Example 3: partial plan with holes

```json
{
  "inputs": [{"name": "url", "type": "string"}],
  "outputs": [{"name": "summary", "type": "string"}],
  "nodes": [
    {"id": "render", "op": "template.render", "config": {"template": "Summarize: {{text}}"}}
  ],
  "edges": [{"from": "input.url", "to": "render.text"}],
  "graph_outputs": {"summary": "render.rendered"},
  "holes": [
    {"node_id": "(missing)", "kind": "missing_skill", "description": "No skill to fetch URL content"}
  ]
}
```"""


def build_planning_context(request: PlanRequest) -> str:
    """Format a PlanRequest into a structured planning prompt.

    The prompt instructs the LLM to return a single JSON object
    conforming to the Graphsmith planning output contract.
    """
    lines: list[str] = []
    lines.append(f"[graphsmith-planner-prompt {PROMPT_VERSION}]\n")

    # Goal
    lines.append(f"# Goal\n{request.goal}\n")

    # Constraints
    if request.constraints:
        lines.append("# Constraints")
        for c in request.constraints:
            lines.append(f"- {c}")
        lines.append("")

    # Desired outputs
    if request.desired_outputs:
        lines.append("# Desired outputs")
        for f in request.desired_outputs:
            lines.append(f"- {f.name}: {f.type}")
        lines.append("")

    # Available skills with required/optional annotations
    lines.append("# Available skills")
    if not request.candidates:
        lines.append("(none — use primitive ops only)\n")
    else:
        for entry in request.candidates:
            ins_parts: list[str] = []
            for name in entry.required_input_names:
                ins_parts.append(f"{name} (required)")
            for name in entry.optional_input_names:
                ins_parts.append(f"{name} (optional)")
            # Fallback for old index entries without required/optional split
            if not ins_parts:
                ins_parts = list(entry.input_names)
            ins = ", ".join(ins_parts) or "(none)"
            outs = ", ".join(entry.output_names) or "(none)"
            effs = ", ".join(entry.effects) or "pure"
            lines.append(
                f"- {entry.id}@{entry.version}: {entry.description}\n"
                f"  inputs: [{ins}]  outputs: [{outs}]  effects: [{effs}]"
            )
        lines.append("")

    # Primitive ops
    ops = sorted(PRIMITIVE_OPS)
    lines.append(f"# Allowed primitive ops\n{', '.join(ops)}\n")

    # Output contract with examples only
    lines.append(_OUTPUT_CONTRACT)

    return "\n".join(lines)


def get_system_message() -> str:
    """Return the system message for providers that support it."""
    return _SYSTEM_MESSAGE
