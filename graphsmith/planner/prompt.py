"""Build a structured planning prompt for the planner backend.

[graphsmith-planner-prompt v3]
"""
from __future__ import annotations

from graphsmith.constants import PRIMITIVE_OPS
from graphsmith.planner.models import PlanRequest

PROMPT_VERSION = "v7"

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
- "outputs" must include every result the goal explicitly requests.
  If the goal says "normalize AND extract keywords", expose BOTH normalized and keywords.
  If the goal says "normalize and THEN summarize", only summary is requested —
  normalized is just a step toward it and should stay internal.
  Key test: does the goal name this result as something the user wants back?
- Recognize paraphrases of skill actions as output requests:
  "tidy up" / "clean" = normalize (output: normalized)
  "find topics" / "list keywords" = extract keywords (output: keywords)
  "write a summary" / "condense" = summarize (output: summary)
  If the goal mentions an action by ANY name, the result is a requested deliverable.
  These mappings apply even in multi-step goals. "Clean up, extract topics, and
  format with a header" = normalize + extract_keywords + formatting = 3 steps.
  Do NOT skip the cleanup/normalize step just because other steps follow it.
- When the goal lists multiple actions with "and" or commas ("X, Y, and Z"),
  each action names a deliverable the user wants back.
- ALWAYS name each output using the skill's actual output port name, even if the
  goal uses different words. Check the skill's "outputs" list in the candidate info
  and use EXACTLY those names. Examples:
  Goal says "topics" → skill outputs ["keywords"] → name it "keywords"
  Goal says "name and value" → skill outputs ["selected"] → name it "selected" (one object)
  Goal says "clean text" → skill outputs ["normalized"] → name it "normalized"
  NEVER invent output names from the goal. NEVER split a single skill output into
  multiple graph outputs. Use the skill's exact port names.
- MINIMAL COMPOSITION: do NOT add formatting, joining, or rendering nodes unless
  the goal explicitly asks for formatting, a list, a header, or presentation.
  "Extract keywords" → use text.extract_keywords.v1 ONLY, output "keywords" directly.
  "Extract keywords and format as a list" → THEN add a formatting node.
- CONSTANTS vs INPUTS: if the goal mentions a fixed string (e.g. "add a header
  saying Results", "format as a bullet list"), that fixed text is a CONSTANT.
  Embed it in a template.render node's config.template — NOT as a graph-level input.
  Only values the user provides at runtime belong in "inputs".
  NEVER use "config.X" as an edge source address. "config" is not a graph scope.
  Edge sources must be "input.X" or "node_id.port".
- ADDRESS SYNTAX: every edge address must be "scope.port" with a dot separator.
  Valid scopes: "input" or an actual node ID from the nodes list.
  INVALID: bare words like "text", "summary", "graph_outputs".
  INVALID: "output.X" — "output" is NOT a valid scope. Graph outputs go in
  "graph_outputs", not as edge destinations.
- GRAPH OUTPUTS: each value in "graph_outputs" must reference an actual node ID
  from the nodes list. If a node is named "count_text", write "count_text.count"
  not "count.count".
- EFFECTS: use ONLY from this list: pure, llm_inference, network_read, network_write,
  filesystem_read, filesystem_write, memory_read, memory_write.
  If unsure, use "pure" for non-LLM skills. Do NOT invent effects.
- EDGE CONFLICTS: each destination port can only receive from ONE source edge.
  Do NOT wire two different edges to the same "node.port".

Use real names and types derived from the goal and available skills.
Never output placeholder tokens or template variables.

## Allowed types
string, integer, number, boolean, bytes, object,
array<string>, array<integer>, array<object>,
optional<string>, optional<integer>

## Example 1: single-skill plan

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

## Example 2a: intermediate hidden — user wants only the final result

Goal: "Normalize text and then summarize it"
The user wants the summary. Normalization is just a step — hide it.

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

## Example 2b: both results exposed — user asks for both

Goal: "Tidy up this text and find the key topics"
"Tidy up" = normalize, "find topics" = extract keywords.
The user wants BOTH. Output names use SKILL PORT NAMES: "normalized" and "keywords".
Even though the goal says "topics", the output is named "keywords" because that is
text.extract_keywords.v1's actual output port.

```json
{
  "inputs": [{"name": "text", "type": "string"}],
  "outputs": [{"name": "normalized", "type": "string"}, {"name": "keywords", "type": "string"}],
  "nodes": [
    {"id": "normalize", "op": "skill.invoke", "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
    {"id": "extract", "op": "skill.invoke", "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}}
  ],
  "edges": [
    {"from": "input.text", "to": "normalize.text"},
    {"from": "normalize.normalized", "to": "extract.text"}
  ],
  "graph_outputs": {"normalized": "normalize.normalized", "keywords": "extract.keywords"},
  "effects": ["llm_inference"]
}
```

## Example 2c: paraphrased multi-output — same as 2b with different wording

Goal: "Clean the text, write a summary, and list the keywords"
"Clean" = normalize, "write a summary" = summarize, "list keywords" = extract keywords.
The user wants summary AND keywords. Normalization is a step — hide it.

```json
{
  "inputs": [{"name": "text", "type": "string"}],
  "outputs": [{"name": "summary", "type": "string"}, {"name": "keywords", "type": "string"}],
  "nodes": [
    {"id": "normalize", "op": "skill.invoke", "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
    {"id": "summarize", "op": "skill.invoke", "config": {"skill_id": "text.summarize.v1", "version": "1.0.0"}},
    {"id": "extract", "op": "skill.invoke", "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}}
  ],
  "edges": [
    {"from": "input.text", "to": "normalize.text"},
    {"from": "normalize.normalized", "to": "summarize.text"},
    {"from": "normalize.normalized", "to": "extract.text"}
  ],
  "graph_outputs": {"summary": "summarize.summary", "keywords": "extract.keywords"},
  "effects": ["llm_inference"]
}
```

## Example 3: extraction → formatting chain

Goal: "Extract keywords and format them as a list"
Chain: extract_keywords produces raw keywords, then join_lines formats them.
The final output uses the formatting skill's port name.

```json
{
  "inputs": [{"name": "text", "type": "string"}],
  "outputs": [{"name": "joined", "type": "string"}],
  "nodes": [
    {"id": "extract", "op": "skill.invoke", "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
    {"id": "format", "op": "skill.invoke", "config": {"skill_id": "text.join_lines.v1", "version": "1.0.0"}}
  ],
  "edges": [
    {"from": "input.text", "to": "extract.text"},
    {"from": "extract.keywords", "to": "format.lines"}
  ],
  "graph_outputs": {"joined": "format.joined"},
  "effects": ["llm_inference"]
}
```

## Example 3b: formatting with a constant header (no extra input)

Goal: "Extract keywords and add a header saying Results"
"Results" is a constant — embed it in config.template, not as a graph input.

```json
{
  "inputs": [{"name": "text", "type": "string"}],
  "outputs": [{"name": "formatted", "type": "string"}],
  "nodes": [
    {"id": "extract", "op": "skill.invoke", "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
    {"id": "format", "op": "template.render", "config": {"template": "Results:\n{{text}}"}}
  ],
  "edges": [
    {"from": "input.text", "to": "extract.text"},
    {"from": "extract.keywords", "to": "format.text"}
  ],
  "graph_outputs": {"formatted": "format.rendered"},
  "effects": ["llm_inference"]
}
```

## Example 3c: JSON skill — use the skill's exact output port name

Goal: "Extract the name and value from this JSON"
json.reshape.v1 outputs ["selected"] (a single object containing the fields).
Do NOT split into separate "name" and "value" outputs. Use "selected".

```json
{
  "inputs": [{"name": "raw_json", "type": "string"}],
  "outputs": [{"name": "selected", "type": "object"}],
  "nodes": [
    {"id": "reshape", "op": "skill.invoke", "config": {"skill_id": "json.reshape.v1", "version": "1.0.0"}}
  ],
  "edges": [
    {"from": "input.raw_json", "to": "reshape.raw_json"}
  ],
  "graph_outputs": {"selected": "reshape.selected"}
}
```

## Example 4: partial plan with holes

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
            tags = ", ".join(entry.tags) if entry.tags else ""
            tag_line = f"  tags: [{tags}]" if tags else ""
            lines.append(
                f"- {entry.id}@{entry.version}: {entry.description}\n"
                f"  inputs: [{ins}]  output_ports: [{outs}]  effects: [{effs}]"
                + (f"\n{tag_line}" if tag_line else "")
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
