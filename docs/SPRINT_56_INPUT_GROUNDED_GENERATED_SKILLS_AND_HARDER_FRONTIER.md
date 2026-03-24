# Sprint 56: Input-Grounded Generated Skills And Harder Frontier

This sprint finished the last gap in the earlier frontier suite and then
replaced that suite with a meaningfully harder one.

## Part 1: Input-grounded generated skills

Some generated skills were still awkward to reuse because their variable
arguments lived in op config instead of on real ports. That made them harder to:

- compose into larger graphs
- inspect structurally
- repair locally
- ground from runtime inputs

This sprint changed several generated text families so their variable arguments
are now explicit inputs:

- `starts_with(text, prefix)`
- `ends_with(text, suffix)`
- `contains(text, substring)`
- `replace(text, old, new)`
- `strip_prefix(text, prefix)`
- `strip_suffix(text, suffix)`

That let the bounded multi-stage fallback solve:

- normalize -> summarize -> contains

and pushed the original frontier suite to `12/12`.

## Part 2: Replace the frontier with harder tasks

The old frontier was no longer a frontier after the recent closed-loop and
composition work, so it was replaced with harder cases that stress:

- cross-domain rewiring
- generated predicates/transforms with extra arguments
- loops plus generated skills
- multi-generated plans
- filesystem boundaries

## New harder frontier baseline

Provider:
- Groq via OpenAI-compatible API
- model: `llama-3.1-8b-instant`

Command:

```bash
conda run -n graphsmith graphsmith eval-frontier \
  --goals evaluation/frontier_goals \
  --registry "$REG" \
  --backend ir \
  --provider openai \
  --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1
```

Observed:
- `6/12`
- `50.0%`

## Important interpretation

This new suite surfaces two different frontiers:

### 1. Real capability boundary

Some cases fail cleanly because the current architecture still lacks:

- robust loop-aware generated-skill composition
- multi-generated capability planning
- external-effect support such as filesystem reads

### 2. Semantic overclaim boundary

Some harder tasks currently register as `success` in the closed-loop harness
even though the bounded fallback may be under-specifying part of the goal.

That means the next frontier is not just “make more tasks executable.”
It is also:

- make frontier evaluation judge semantic fidelity more strictly
- ensure bounded fallbacks do not claim success when they only satisfy a subset
  of the requested intent

## Why this matters for the long-term skill network

If Graphsmith is going to rely on a shared remote skill ecosystem later, the
system cannot just be good at finding *a* plausible graph. It has to be good at
proving that the reused/generated skill composition actually satisfies the full
intent. That makes richer contracts and stronger evaluation as important as
broader retrieval.
