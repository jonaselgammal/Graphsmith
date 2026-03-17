# Sprint 10F — Output Mapping Completeness

## Exact failure observed

```
Skill output(s) not mapped in graph.yaml: keywords
```

The LLM-generated glue graph declared `keywords` in `outputs` but
did not include a corresponding entry in `graph_outputs`.

## Root cause

The prompt's Example 1 itself had this bug: it declared two outputs
(`summary` and `keywords`) but `graph_outputs` only mapped `summary`.
The LLM faithfully reproduced this broken pattern.

## Prompt changes

1. Fix Example 1: `graph_outputs` now maps both `summary` and `keywords`.
2. Add an explicit rule after the required-keys description:
   "Every name in outputs must have a matching entry in graph_outputs."
3. Example 2 already has complete mapping — no change needed.

## Validator message improvement

The error message now says:

> Declared output(s) missing from graph_outputs: keywords.
> Every output declared in "outputs" must have a corresponding
> entry in "graph_outputs" mapping it to a node port.

## Tests added

- Regression: plan with missing graph_outputs entry → partial
- Positive: plan with complete multi-output mapping → success
- Prompt: contains completeness rule text

## Why strict and safe

- The prompt fix corrects a buggy example — the LLM was learning
  from a broken pattern
- The validator is not weakened
- No auto-fill of missing mappings
