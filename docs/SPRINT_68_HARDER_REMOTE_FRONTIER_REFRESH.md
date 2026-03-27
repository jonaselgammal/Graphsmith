# Sprint 68: Harder Remote Frontier Refresh

The previous frontier suite was saturated again after the hosted remote
registry and semantic-fidelity work. This sprint refreshes the suite so it
probes the next boundary more honestly.

## What changed

The new frontier now emphasizes:

- tougher tier-1 success cases around existing-skill plus generated formatting
  or predicate composition
- loop-plus-generated failure probes
- published-only / trusted-published-only prompts that the current planner does
  not yet model explicitly

## Local validation

- `conda run -n graphsmith pytest tests/test_frontier_eval.py -q`
- `6 passed`

## Live hosted-registry run

Against:

- `https://graphsmith-remote-registry.graphsmith.workers.dev`

Using Groq `llama-3.1-8b-instant`:

- `9/12`

### Meaningful failures

- `f01`
  - a near-frontier success case still fails:
    JSON extract -> pretty print -> contains
- `f10`
  - published-only constraint is ignored and a generated skill is still used
- `f11`
  - trusted-published-only constraint is ignored and a generated skill is still
    used

## Why this is useful

This gives a cleaner next frontier:

- one success-side composition gap
- two clear provenance/trust-policy gaps

That lines up directly with the next architectural step:

- planner-visible trust/provenance policy and published-only constraints
