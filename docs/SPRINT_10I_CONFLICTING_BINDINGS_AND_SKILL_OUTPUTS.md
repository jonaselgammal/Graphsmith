# Sprint 10I — Conflicting Bindings and Skill Outputs

## Conflicting-binding issue

The saved real-LLM plan has two edges targeting the same port:

```
input.text         → extract.text
normalize.normalized → extract.text
```

These are **conflicting bindings** — two different source addresses
for the same destination port `extract.text`.

### Current behavior

- **Validator**: does NOT check for destination-port conflicts.
  The plan passes validation.
- **Executor**: `_build_bindings()` detects the conflict at runtime
  and raises `ExecutionError`, but the error is wrapped in nested
  `Execution failed at node` messages, making it hard to diagnose.

### Fix

Move destination-port conflict detection from executor to
**validator**. This catches the issue before execution, with a
clear error message:

> Conflicting edges: port 'text' on node 'extract' is targeted by
> multiple edges from different sources: 'input.text' and
> 'normalize.normalized'.

The executor check remains as a defense-in-depth belt.

## Nested skill output propagation

`skill.invoke` returns the sub-skill's `graph_outputs` as the
node's output ports. For `text.extract_keywords.v1`:
- graph outputs: `{"keywords": "extract.text"}`
- so `skill.invoke` node outputs: `{"keywords": "..."}`
- stored in value store as `extract_kw_node.keywords`

This is correct. The sub-skill's output port names become the
`skill.invoke` node's output port names.

## text.extract_keywords.v1 correctness

The skill is correctly defined:
- input: `text` (required)
- output: `keywords` (type: string)
- graph: `template.render` → `llm.generate`
- graph output maps `keywords` to `extract.text` (the llm.generate
  node's text output port)

No bug in the skill definition.

## The "summary" output mismatch

The user saw `{"summary": "Summarize the following text in  sentences:..."}`
from a different `plan-and-run` invocation. That output came from
a plan that used `text.summarize.v1` (not the saved plan). The
mock planner picks the first candidate, which varies by registry
contents and search order. This is not a bug — different runs can
produce different plans.

## Why strict and safe

- Conflicting bindings are caught at validation time, not runtime
- No silent conflict resolution (e.g. "last edge wins")
- Skill output propagation is already correct
- The fix is a validator check, not a parser/planner change
