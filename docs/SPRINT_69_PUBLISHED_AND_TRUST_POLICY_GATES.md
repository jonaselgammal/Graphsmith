# Sprint 69: Published And Trust Policy Gates

This sprint adds the first planner-visible policy layer for remote skill
provenance constraints.

## What changed

- added `graphsmith/planner/policy.py` to derive explicit goal-level policy
  constraints from natural language:
  - `published-only`
  - `trusted published only`
- retrieval now filters candidate lists against those policies when registry
  metadata is available
- `compose_plan()` now injects derived goal constraints into `PlanRequest`, so
  the normal planner prompt can see them
- closed-loop planning now:
  - passes derived policy constraints into planner requests
  - filters candidate lists with the same policy rules
  - blocks generated-skill success paths when the goal explicitly forbids them

## Why

The refreshed remote frontier exposed a real gap:

- `f10`: published-only constraint ignored
- `f11`: trusted-published-only constraint ignored

The system already carried provenance fields in `IndexEntry`, but nothing was
deriving those constraints from the goal or enforcing them during retrieval and
closed-loop fallback.

## Validation

Focused regressions:

```bash
conda run -n graphsmith pytest tests/test_planner.py tests/test_closed_loop.py tests/test_frontier_eval.py -q
conda run -n graphsmith python -m compileall graphsmith
```

Result:

- `57 passed`

Live hosted frontier run against:

- `https://graphsmith-remote-registry.graphsmith.workers.dev`
- Groq `llama-3.1-8b-instant`

Result:

- `11/12`

Meaningful deltas:

- `f10` now passes by failing cleanly with `semantic_fidelity_blocked`
- `f11` now passes by failing cleanly with `semantic_fidelity_blocked`

## New frontier

The remaining miss is now a real success-side composition gap:

- `f01`: `json.extract_field -> json.pretty_print -> text.contains`

So the next step is no longer provenance policy. It is improving mixed
existing-skill plus generated-predicate composition on the success side.
