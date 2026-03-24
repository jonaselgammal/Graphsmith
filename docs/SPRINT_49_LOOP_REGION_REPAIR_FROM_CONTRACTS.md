# Sprint 49 — Loop Region Repair From Contracts

## Summary

This sprint strengthens loop repair without moving yet into full local subgraph
regeneration.

The key idea is simple:
- if a loop body is a single-output skill invocation,
- and the graph asks for a named collected loop output,
- Graphsmith can infer that name from the skill contract instead of waiting for
  the planner to spell out the loop body contract perfectly.

That gives a more structural loop repair path before execution and one extra
runtime fallback when a named loop output was requested but only `results` was
materialized.

## What changed

### 1. Registry-aware loop output inference

[graphsmith/planner/graph_repair.py](/Users/jeg/Documents/graphsmith-pack/graphsmith/planner/graph_repair.py)
can now infer named `parallel.map` outputs from fetched skill contracts.

Current supported case:
- `parallel.map` with `op = skill.invoke`
- `op_config.skill_id` and `version` resolve in the registry
- the invoked skill has exactly one declared output

Example:
- loop body invokes `text.normalize.v1`
- fetched contract says the only output is `normalized`
- graph can align `results` or `mapped` to `normalized`

### 2. Runtime repair can enable named loop outputs

If execution proves:
- the graph requested `loop_node.normalized`
- but only `loop_node.results` exists

Graphsmith can now:
- confirm from the loop body contract that `normalized` is the only valid named
  collected field
- enable `aggregate_outputs`
- retry once

This is still bounded repair, not general loop-body regeneration.

### 3. Compose-time validation uses registry-aware repair

[graphsmith/planner/composer.py](/Users/jeg/Documents/graphsmith-pack/graphsmith/planner/composer.py)
now passes the registry into graph normalization during plan validation, not
only during execution.

That means saved plans and CLI `plan` output benefit from the same loop-region
repair when the skill contract is available.

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
- `206 passed`

## Live check

Anthropic crowded-registry loop goal:

```text
For each string in the input list, normalize it and return all normalized strings.
```

Observed result:

```json
{
  "normalized": ["hello", "world"]
}
```

## Why this matters

This is the first step toward real loop-region repair rather than only generic
graph cleanup:
- the system now uses the loop body contract itself
- the repair stays local to the loop node
- the fix does not require replanning the whole graph

## Next step

Move from contract-only loop repair to true local subgraph regeneration:
- isolate a failing branch or loop region
- regenerate only that region
- preserve the rest of the validated graph
