# Sprint 48 — Output Contract Repair

## Summary

This sprint moves the next major boundary from loop execution to loop output
fidelity.

The system already had:
- loop lowering
- graph normalization
- runtime retry
- live execution on crowded registries

What was still weak was the final external contract. In live loop runs, the
plan could execute correctly but return a generic collection key like `mapped`
or `results` instead of the user-relevant output name like `normalized`.

This sprint adds a bounded output-contract repair layer for that case.

## What changed

### 1. Graph normalization now aligns generic loop outputs

Extended [graphsmith/planner/graph_repair.py](/Users/jeg/Documents/graphsmith-pack/graphsmith/planner/graph_repair.py).

New behavior:
- if a `parallel.map` wraps a single-output inner op and the graph exposes a
  generic collection alias like `results` or `mapped`, the graph can rewrite
  that to the named collected output
- if the graph already uses the right external output name but still points at
  the generic collection port, the graph rewrites the final output address
- when needed, it also enables `aggregate_outputs` so the named collected output
  actually exists at runtime

This is intentionally narrow:
- only `parallel.map`
- only generic collection aliases
- only when the inner output name is deterministic from the loop contract

### 2. New tests for output alignment

Added regressions in [tests/test_plan_execution.py](/Users/jeg/Documents/graphsmith-pack/tests/test_plan_execution.py):
- generic loop output name `results -> normalized`
- correct loop output name but generic port `normalize_all.results -> normalize_all.normalized`
- preservation of existing generic `result` behavior where the repair would
  otherwise change semantics instead of just align contracts

## Validation

```bash
conda run -n graphsmith pytest \
  tests/test_parallel_map.py \
  tests/test_planning_ir.py \
  tests/test_plan_execution.py \
  tests/test_runtime.py \
  tests/test_cli.py \
  tests/test_registry.py \
  tests/test_retrieval_diagnostics.py -q

conda run -n graphsmith python -m compileall graphsmith
```

Observed result:
- `204 passed`

## Live crowded-registry checks

Registry:
- all 15 example skills published into a temp local registry

Provider:
- Anthropic `claude-sonnet-4-20250514`

### Before this sprint

Loop-style goal:
- `"For each string in the input list, normalize it and return all normalized strings."`

Possible failure/output shapes:
- runtime failures from malformed loop contracts
- successful execution but output returned under `mapped`
- successful planning but generic output contract drift

### After this sprint

Same live goal now returns:

```json
{
  "normalized": ["hello", "world"]
}
```

Observed live `plan` repairs for one representative run:
- rename `array.map` source `array -> items`
- lift `array.map` operation `text.normalize -> parallel.map`
- enable aggregated named outputs for `parallel.map`
- align generic output `mapped -> normalized`

## Crowded-registry evaluation

`eval-planner` on `evaluation/challenge_goals` remains:
- `11/12`
- `avg_candidates = 3.9`

That is useful signal:
- the loop output-fidelity issue is no longer the main blocker
- retrieval remains stable under distractor pressure
- the remaining challenge miss is elsewhere

## Takeaway

The system now has a clearer layered repair story:
- IR-local repair
- graph contract normalization
- runtime retry
- output-contract repair

That makes live loop planning materially more reliable without needing to
replan the whole graph.

## Next step

The next sensible target is broader semantic output alignment:
- multi-output plans where one output is renamed semantically
- constant/config-related output drift
- eventually a small evaluation battery designed specifically to separate:
  1. retrieval failures
  2. structural graph failures
  3. output-contract fidelity failures
