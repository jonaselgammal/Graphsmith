# Sprint 10D — Real LLM Type Debugging

## Exact failure observed

Error: `Unknown parameterised type '' in field '<str>'`

The LLM copied the schema placeholder `"type": "<str>"` literally
from the prompt template instead of substituting a real type.

## Root cause

The prompt's schema template used angle-bracket placeholders:

```
"inputs": [{"name": "<str>", "type": "<str>"}]
```

The LLM treated `<str>` as a literal value. The validator then
parsed `<str>` as a parameterised type: outer=`` (empty string
before `<`), inner=`str` → "Unknown parameterised type ''".

This is a **prompt design bug**, not a parser or validator bug.

## Prompt changes

Replace all `<str>` / `<name>` / `<node_id>` angle-bracket
placeholders with descriptive words in CAPS or quoted descriptions
that cannot be confused with parameterised type syntax:

Before: `"type": "<str>"`
After:  `"type": "TYPE"`

The schema section now uses:

```
{
  "inputs":        [{"name": "NAME", "type": "TYPE"}],
  "outputs":       [{"name": "NAME", "type": "TYPE"}],
  "nodes":         [{"id": "NODE_ID", "op": "OP_NAME", "config": {}}],
  "edges":         [{"from": "input.NAME", "to": "NODE_ID.PORT"}],
  "graph_outputs": {"OUTPUT_NAME": "NODE_ID.PORT"}
}
```

No angle brackets. No ambiguity with the type grammar.

## Validator diagnostic improvement

The validator error for malformed parameterised types now includes
the exact raw type value:

```
Malformed type '<str>' in field 'keywords': '' is not a valid
parameterised type. Only 'array' and 'optional' accept type
parameters (e.g. array<string>).
```

## Debug plan saving

`plan-and-run` and `plan` gain a `--save-on-failure PATH` option.
When a plan fails (partial/failure), the raw PlanResult JSON is
saved to the specified file for inspection. This makes real-LLM
debugging straightforward without changing the normal output path.

## Why strict and safe

- The fix is prompt-side: remove ambiguous placeholders
- The validator is not weakened — it still rejects `<str>`
- No fuzzy repair: `<str>` does not get silently coerced to `string`
- The debug flag saves the failing plan for inspection, not repair
