# Sprint 10E — Placeholder Elimination

## Why placeholder tokens are problematic

LLMs treat prompt content as training signal for their output format.
When the prompt contains an abstract schema with tokens like `NAME`,
`TYPE`, `NODE_ID`, the LLM copies them literally into its response
instead of substituting real values.

This happened twice:
1. `<str>` — angle-bracket placeholders copied as parameterised types
2. `NAME` / `TYPE` — CAPS placeholders copied as literal field values

The solution is to never show abstract placeholders in the output
format section. Use only concrete, fully-filled examples.

## How the prompt is changed

The abstract schema template is removed entirely. The output contract
now consists of:
1. A short prose description of the required keys
2. Two concrete examples (already present, kept as-is)
3. An explicit instruction: "Use real names and types from the goal
   and available skills. Never output placeholder tokens."

No abstract template. No `NAME`, `TYPE`, `NODE_ID`, `OP_NAME`, `PORT`.

## Validator placeholder diagnostics

The validator now detects common placeholder tokens in type fields
and produces a specific error:

> Type 'TYPE' in field 'NAME' looks like a placeholder token
> copied from a template. Use a real type: string, integer, ...

This catches: `TYPE`, `NAME`, `NODE_ID`, `OP_NAME`, `PORT`,
`OUTPUT_NAME`, `STR`, `STRING_TYPE`.

## Why strict and safe

- The prompt change removes the source of confusion
- The validator is not weakened — placeholder tokens are invalid types
- No automatic replacement of `TYPE` → `string`
- The diagnostic just makes the error message more helpful
