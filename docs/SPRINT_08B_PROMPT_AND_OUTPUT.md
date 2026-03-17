# Sprint 08B — Prompt and Output Reliability

## Planning prompt structure

The prompt has four sections, in order:

1. **System framing** — role, task type, output format requirement
2. **Context** — goal, constraints, desired outputs, available skills
3. **Output contract** — exact JSON schema with required keys,
   one valid example, one partial-plan example
4. **Primitive ops reference** — allowed ops list for the LLM

The prompt is kept under ~2000 tokens excluding candidate skill listings.

## Prompt template versioning

The prompt includes a version tag:
```
[graphsmith-planner-prompt v1]
```

This is embedded in the prompt text and exposed as
`graphsmith.planner.prompt.PROMPT_VERSION = "v1"`.

Version changes when the prompt contract changes in a
backward-incompatible way.

## Structured-output instructions

The prompt ends with an explicit contract:

> Respond with ONLY a JSON object. No explanation before or after.
> The JSON must have these required keys: inputs, outputs, nodes,
> edges, graph_outputs.

This instruction is provider-agnostic — it works for all LLMs.

## Provider-specific JSON-output hints

| Provider | Hint |
|----------|------|
| Anthropic | System message: "You are a graph planner. Respond with JSON only." |
| OpenAI-compatible | `response_format: {"type": "json_object"}` in request body |
| Echo | None (test double) |

These hints are applied at the provider transport layer, not in the
prompt text. The parser remains provider-agnostic.

## Common LLM output quirks handled

The parser applies these extractions in order:

1. If the entire response is a valid JSON object → use it directly
2. If the response contains a fenced code block (` ```json ... ``` `
   or ` ``` ... ``` `) → extract the block content
3. If the response has leading/trailing prose around a JSON object
   → extract the first `{...}` balanced block

Each extraction is deterministic. If none match, fail with a
structured error.

## What remains intentionally strict

- All five required keys must be present
- Node `id` and `op` must be present
- Edge `from` and `to` must be present
- Unknown hole `kind` values are normalized, not rejected
- Unknown top-level keys are ignored (forward-compatible)
- Truncated or malformed JSON is never repaired

## Explicit limitations

- Single-shot only — no retry, no multi-turn
- No provider-specific prompt variants
- No token budget management
- Prompt version is informational, not enforced by the parser
- The example in the prompt uses `skill.invoke`; the LLM may
  produce plans using any primitive op
