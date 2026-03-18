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
- When the goal lists multiple actions with "and" or commas ("X, Y, and Z"),
  each action names a deliverable the user wants back.
- ALWAYS name each output using the skill's actual output port name, even if the
  goal uses different words. Examples:
  Goal says "topics" → skill text.extract_keywords.v1 outputs "keywords" → name it "keywords"
  Goal says "summary" → skill text.summarize.v1 outputs "summary" → name it "summary"
  Goal says "clean text" → skill text.normalize.v1 outputs "normalized" → name it "normalized"
  NEVER use the goal's phrasing as the output name. Use the skill's port name.
- CONSTANTS vs INPUTS: if the goal mentions a fixed string (e.g. "add a header
  saying Results", "format as a bullet list"), that fixed text is a CONSTANT.
  Embed it in a template.render node's config.template — NOT as a graph-level input.
  Only values the user provides at runtime belong in "inputs".

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

Goal: "Normalize this text and extract keywords"
The user wants BOTH the normalized text AND the keywords. Expose both.

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
                f"  inputs: [{ins}]  outputs: [{outs}]  effects: [{effs}]"
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
