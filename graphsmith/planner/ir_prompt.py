"""Build a structured planning prompt that asks the LLM to emit Planning IR.

The IR prompt is simpler than the direct graph prompt because the LLM
only needs to express semantic intent (steps, data flow, config), not
exact graph structure (node IDs, edge syntax, graph_outputs mapping).
"""
from __future__ import annotations

from graphsmith.constants import PRIMITIVE_OPS
from graphsmith.planner.models import PlanRequest

IR_PROMPT_VERSION = "ir-v3"

_IR_SYSTEM_MESSAGE = (
    "You are a Graphsmith plan designer. "
    "You describe plans as a sequence of steps using available skills and primitive ops. "
    "Respond with JSON only. No explanation before or after the JSON."
)

_IR_OUTPUT_CONTRACT = """\
# Required output format

Respond with ONLY a JSON object. No prose, no markdown, no explanation.

Required keys: "inputs", "steps", "final_outputs".
Optional keys: "effects", "reasoning".

## Schema

```json
{
  "inputs": [{"name": "...", "type": "..."}],
  "steps": [
    {
      "name": "step_name",
      "skill_id": "text.summarize.v1",
      "version": "1.0.0",
      "sources": {
        "input_port": {"step": "input", "port": "graph_input_name"},
        "other_port": {"step": "other_step_name", "port": "output_port"}
      },
      "config": {}
    }
  ],
  "final_outputs": {
    "output_name": {"step": "step_name", "port": "output_port"}
  },
  "effects": ["llm_inference"]
}
```

## Rules

- "inputs": only include inputs the user would provide. Do NOT add optional skill inputs
  unless the goal explicitly requires them.
- "steps": one entry per skill/op invocation.
  - "name": a SHORT single-word ID (e.g. "extract", "format", "normalize", "summarize").
    Do NOT use the full skill ID as the name. Do NOT use dots or spaces.
    GOOD: "extract", "format", "normalize"
    BAD: "text.extract_keywords", "extract-keywords", "step 1"
  - "skill_id": the full skill ID EXACTLY as listed in available skills. Do NOT append
    @version to skill_id. The version goes in the separate "version" field.
    CORRECT: "skill_id": "text.summarize.v1", "version": "1.0.0"
    WRONG: "skill_id": "text.summarize.v1@1.0.0"
  - "sources": maps each INPUT PORT of the skill to where it gets its data
  - "config": static configuration (e.g. template strings for template.render)

## FINAL OUTPUT NAMING — CRITICAL

Each key in "final_outputs" MUST match the output port name of the step that
produces it. Check each skill's "output_ports" listing and use that name.
The key and the port MUST be identical.

WRONG: {"cleaned_text": {"step": "title", "port": "titled"}}
RIGHT: {"titled": {"step": "title", "port": "titled"}}

WRONG: {"output": {"step": "reshape", "port": "selected"}}
RIGHT: {"selected": {"step": "reshape", "port": "selected"}}

Do NOT invent output names. Do NOT use generic names like "output", "result",
"cleaned_text", or "formatted_text".

- "effects": from this list only: pure, llm_inference, network_read, network_write,
  filesystem_read, filesystem_write, memory_read, memory_write.

## STEP COUNT — how many steps to use

Count your steps BEFORE writing JSON. Follow these rules exactly:

- Plain extraction/analysis with NO formatting request → EXACTLY 1 step, NO extra steps
  "Extract keywords" → 1 step (extract_keywords only)
  "Find the key topics" → 1 step (extract_keywords only)
  "Summarize this text" → 1 step (summarize only)
  "Analyze the sentiment" → 1 step (classify_sentiment only)
  "Count the words" → 1 step (word_count only)
  "Normalize this text" → 1 step (normalize only)
  "Just lowercase and trim" → 1 step (normalize only)
  Do NOT add join_lines, template.render, or any formatting step to these!

- Chain where intermediate results are hidden → N skill steps
  "Normalize and then summarize" → 2 steps (normalize + summarize), expose summary only
  "Clean up and extract keywords" → 2 steps, expose both if goal says "and"

- Explicit formatting/presentation request → extraction + formatting step
  "Format as a list" / "bullet list" → use text.join_lines.v1
  "Add a header saying X" / "format with a header" → use template.render
  "Make a bullet list" → 2 steps (extract + join_lines)

- Multi-action goals with "and" listing deliverables → expose ALL results
  "Normalize and extract keywords" → 2 steps, expose normalized AND keywords
  "Summarize and classify sentiment" → 2 steps, expose summary AND sentiment
  "Clean, capitalize, and extract" → 3 steps, expose titled AND keywords

IF the goal does NOT contain words like "format", "list", "header", "present",
"bullet", "table", or "readable" → do NOT add formatting steps.
"find topics" / "extract keywords" / "tidy up and find topics" → NO formatting.

## PARAPHRASE → SKILL MAPPING

If the goal uses informal language, map it to the correct skill:
- "clean up" / "tidy up" / "normalize" / "lowercase and trim" → text.normalize.v1
- "find topics" / "key topics" / "extract keywords" → text.extract_keywords.v1
- "summarize" / "condense" / "brief summary" → text.summarize.v1
- "capitalize" / "title case" / "capitalize each word" → text.title_case.v1
- "sentiment" / "analyze sentiment" → text.classify_sentiment.v1
- "count words" / "how many words" → text.word_count.v1

If the goal says "clean" or "tidy", you MUST include a normalize step.
Do NOT skip it even if other steps follow.

## CONSTANTS

Fixed strings from the goal (e.g. "Results", "Summary:") go in a template.render
step's config.template field. NEVER create graph inputs for constants.

## Examples

### Example 1: single skill — summarize
Goal: "Summarize this text"
Steps: 1. final_outputs uses port name "summary".
```json
{
  "inputs": [{"name": "text", "type": "string"}],
  "steps": [
    {"name": "summarize", "skill_id": "text.summarize.v1", "version": "1.0.0",
     "sources": {"text": {"step": "input", "port": "text"}}}
  ],
  "final_outputs": {"summary": {"step": "summarize", "port": "summary"}},
  "effects": ["llm_inference"]
}
```

### Example 2: single skill — extract keywords (NO formatting)
Goal: "Extract keywords from this text" / "Find the key topics"
Steps: 1 (extract only — no formatting step!). final_outputs uses "keywords".
```json
{
  "inputs": [{"name": "text", "type": "string"}],
  "steps": [
    {"name": "extract", "skill_id": "text.extract_keywords.v1", "version": "1.0.0",
     "sources": {"text": {"step": "input", "port": "text"}}}
  ],
  "final_outputs": {"keywords": {"step": "extract", "port": "keywords"}},
  "effects": ["llm_inference"]
}
```

### Example 3: chain — normalize then summarize
Goal: "Normalize this text and then summarize it"
Steps: 2. Normalize is internal, expose only "summary".
```json
{
  "inputs": [{"name": "text", "type": "string"}],
  "steps": [
    {"name": "normalize", "skill_id": "text.normalize.v1", "version": "1.0.0",
     "sources": {"text": {"step": "input", "port": "text"}}},
    {"name": "summarize", "skill_id": "text.summarize.v1", "version": "1.0.0",
     "sources": {"text": {"step": "normalize", "port": "normalized"}}}
  ],
  "final_outputs": {"summary": {"step": "summarize", "port": "summary"}},
  "effects": ["llm_inference"]
}
```

### Example 4: multi-output — "tidy up and find topics"
Goal: "Tidy up this text and find the key topics"
"tidy up" = normalize, "find topics" = extract_keywords. Expose BOTH.
final_outputs uses port names: "normalized" and "keywords".
```json
{
  "inputs": [{"name": "text", "type": "string"}],
  "steps": [
    {"name": "normalize", "skill_id": "text.normalize.v1", "version": "1.0.0",
     "sources": {"text": {"step": "input", "port": "text"}}},
    {"name": "extract", "skill_id": "text.extract_keywords.v1", "version": "1.0.0",
     "sources": {"text": {"step": "normalize", "port": "normalized"}}}
  ],
  "final_outputs": {"normalized": {"step": "normalize", "port": "normalized"},
                     "keywords": {"step": "extract", "port": "keywords"}},
  "effects": ["llm_inference"]
}
```

### Example 5: cleanup + capitalize
Goal: "Clean up this text and capitalize each word"
"clean up" = normalize, "capitalize" = title_case. Expose "titled".
```json
{
  "inputs": [{"name": "text", "type": "string"}],
  "steps": [
    {"name": "normalize", "skill_id": "text.normalize.v1", "version": "1.0.0",
     "sources": {"text": {"step": "input", "port": "text"}}},
    {"name": "title", "skill_id": "text.title_case.v1", "version": "1.0.0",
     "sources": {"text": {"step": "normalize", "port": "normalized"}}}
  ],
  "final_outputs": {"titled": {"step": "title", "port": "titled"}},
  "effects": ["pure"]
}
```

### Example 6: formatting with constant header (template.render)
Goal: "Extract keywords and add a header saying Results"
Steps: 2 (extract + template.render). Expose "rendered".
```json
{
  "inputs": [{"name": "text", "type": "string"}],
  "steps": [
    {"name": "extract", "skill_id": "text.extract_keywords.v1", "version": "1.0.0",
     "sources": {"text": {"step": "input", "port": "text"}}},
    {"name": "format", "skill_id": "template.render", "version": "1.0.0",
     "sources": {"text": {"step": "extract", "port": "keywords"}},
     "config": {"template": "Results:\\n{{text}}"}}
  ],
  "final_outputs": {"rendered": {"step": "format", "port": "rendered"}},
  "effects": ["llm_inference"]
}
```

### Example 7: extraction + formatting as list
Goal: "Extract keywords and format them as a list"
Steps: 2 (extract + join_lines). Expose "joined" (join_lines port name).
```json
{
  "inputs": [{"name": "text", "type": "string"}],
  "steps": [
    {"name": "extract", "skill_id": "text.extract_keywords.v1", "version": "1.0.0",
     "sources": {"text": {"step": "input", "port": "text"}}},
    {"name": "format", "skill_id": "text.join_lines.v1", "version": "1.0.0",
     "sources": {"lines": {"step": "extract", "port": "keywords"}}}
  ],
  "final_outputs": {"joined": {"step": "format", "port": "joined"}},
  "effects": ["llm_inference"]
}
```
"""


def build_ir_planning_context(request: PlanRequest) -> str:
    """Format a PlanRequest into a prompt that elicits Planning IR."""
    lines: list[str] = []
    lines.append(f"[graphsmith-planner-prompt {IR_PROMPT_VERSION}]\n")

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

    # Available skills
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

    # Output contract
    lines.append(_IR_OUTPUT_CONTRACT)

    return "\n".join(lines)


def get_ir_system_message() -> str:
    """Return the system message for IR-based planning."""
    return _IR_SYSTEM_MESSAGE
