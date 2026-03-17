# Sprint 07A — Planner Output Parsing

## Raw planner output format

The LLM planner backend expects a **JSON object** in the provider response.
No YAML. No free-form text wrapping. The JSON may optionally be enclosed
in a Markdown code fence (` ```json ... ``` `) which the parser strips.

### Required top-level keys

```json
{
  "inputs": [ {"name": "text", "type": "string"} ],
  "outputs": [ {"name": "summary", "type": "string"} ],
  "nodes": [
    {
      "id": "step1",
      "op": "skill.invoke",
      "config": {"skill_id": "text.summarize.v1", "version": "1.0.0"}
    }
  ],
  "edges": [
    {"from": "input.text", "to": "step1.text"}
  ],
  "graph_outputs": {
    "summary": "step1.summary"
  }
}
```

| Key | Type | Required | Maps to |
|-----|------|----------|---------|
| `inputs` | `list[{name, type, required?}]` | yes | `GlueGraph.inputs` |
| `outputs` | `list[{name, type}]` | yes | `GlueGraph.outputs` |
| `nodes` | `list[{id, op, config?, inputs?}]` | yes | `GraphBody.nodes` |
| `edges` | `list[{from, to}]` | yes | `GraphBody.edges` |
| `graph_outputs` | `dict[str, str]` | yes | `GraphBody.outputs` |

### Optional top-level keys

| Key | Type | Maps to |
|-----|------|---------|
| `effects` | `list[str]` | `GlueGraph.effects` (default: `["pure"]`) |
| `holes` | `list[{node_id, kind, description}]` | `PlanResult.holes` |
| `reasoning` | `str` | `PlanResult.reasoning` |

## Parsing rules

1. **Strip code fences**: if the response starts with ` ```json ` or ` ``` `,
   extract the content between fences.
2. **Parse JSON**: `json.loads()` on the stripped text.
3. **Validate required keys**: all five required keys must be present.
4. **Build models**: construct `IOField`, `GraphNode`, `GraphEdge`, `GraphBody`,
   `GlueGraph` from the parsed data.
5. **Extract holes**: if `holes` key is present, parse into `UnresolvedHole` list.

## Validation rules

After parsing, the resulting `GlueGraph` is wrapped in a synthetic
`SkillPackage` and run through `validate_skill_package()`.

- If parsing succeeds and validation succeeds: `status="success"`
- If parsing succeeds but validation fails: `status="partial"`,
  validation error added as a hole
- If parsing succeeds and holes are present from the LLM: `status="partial"`

## Fallback behavior on malformed output

- **Not JSON**: return `status="failure"`, raw text in reasoning,
  `parsing_error` hole with the JSON decode error message.
- **Missing required keys**: return `status="failure"`, list missing
  keys in the hole description.
- **Invalid model data**: return `status="failure"`, include the
  Pydantic validation error in the hole description.

No silent recovery. No guessing. Every failure is typed and inspectable.

## Explicit limitations

- Only JSON is accepted, no YAML.
- No multi-message or streaming support.
- No retry on parse failure — one shot.
- The parser does not attempt to fix or complete partial JSON.
- Edge aliases: `from` is the JSON key (not `from_`).
- `required` field on inputs defaults to `true` if omitted.
- Unknown keys in the JSON are silently ignored (forward-compatible).
