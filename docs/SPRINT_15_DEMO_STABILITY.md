# Sprint 15 — Demo Stability

## How demo plans are generated

The planner can generate glue graphs from natural language goals,
but the mock planner naively picks the first alphabetical candidate.
Real LLM planners produce varied output across runs.

For reproducible demos, **saved plans** are preferred.

## When saved plans are preferred

- README canonical demo: always use saved plans
- CI verification: always use saved plans
- Live presentations: always use saved plans
- Exploration / experimentation: live planning is fine

## Saved plan location

```
examples/plans/
  normalize_extract_keywords.json     # normalize → extract keywords
  normalize_summarize_keywords.json   # normalize → summarize → extract keywords
```

These are first-class `GlueGraph` JSON files created via
`graphsmith plan --save`. They can be executed with `graphsmith run-plan`.

## Mock LLM vs real LLM output

| Component | Mock LLM | Real LLM |
|-----------|----------|----------|
| text.normalize | deterministic (lowercase, strip) | same (pure op) |
| text.extract_keywords | echoes the prompt | comma-separated keywords |
| text.summarize | echoes the prompt | concise summary |
| Plan structure | identical | identical |
| Plan execution | deterministic | LLM output varies |

The saved plans work identically with both mock and real providers.
Only the LLM node outputs differ.
