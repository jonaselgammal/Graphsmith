# Sprint 57: Semantic Fidelity Gates

The harder frontier suite exposed a new class of problem: bounded fallbacks were
sometimes returning `success` for graphs that were executable but only covered a
subset of the requested intent.

This sprint tightened those gates.

## What changed

- added `match_template_keys()` to the autogen layer so Graphsmith can detect
  when a goal matches multiple generated capabilities
- blocked bounded multi-stage fallback for loop-shaped goals
- blocked bounded multi-stage fallback for goals that clearly require multiple
  generated skills

## Why this matters

The system is no longer only limited by whether it can build a graph.
It is also limited by whether that graph is faithful to the user intent.

That matters directly for the long-term remote skill ecosystem vision: a shared
AI-native repository only helps if reused skills can be composed with strong
semantic guarantees, not just structural plausibility.

## Validation

```bash
conda run -n graphsmith pytest tests/test_autogen.py tests/test_closed_loop.py \
  tests/test_frontier_eval.py tests/test_cli.py -q
```

Observed:
- `134 passed`

## Harder frontier baseline

Using the refreshed harder frontier suite with Groq `llama-3.1-8b-instant` on a
clean example-only registry:

- `8/12`
- `66.7%`

Important interpretation:

- this is a more honest frontier than the previous `50%` run because several
  earlier “successes” were actually semantic overclaims
- the remaining boundary is now centered on:
  - loop-aware generated-skill composition
  - cases where the planner already sees an exact generated skill but still
    cannot re-enter composition cleanly
  - stricter evaluation of intent coverage
