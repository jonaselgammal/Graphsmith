# Sprint 47 — Graph Normalization and Runtime Repair

## Summary

This sprint extends the first repair layer into the compiled graph and runtime.

The key change is that Graphsmith now tries to preserve a semantically good plan
even when the emitted graph still contains legacy or partially malformed loop
contracts. Instead of forcing a full replan, the system can now normalize the
graph, retry a narrow runtime patch once, and surface those actions explicitly.

## What changed

### 1. Graph-level contract normalization

Added `graphsmith/planner/graph_repair.py` and integrated it in:
- `compose_plan()` validation path
- `run_glue_graph()` execution path

Current normalization scope:
- rewrite `array.map` / `parallel.map` input alias `array -> items`
- lift `parallel.map` shorthand like `operation: "text.normalize"` into
  runtime config
- flatten nested `parallel.map` `skill.invoke` targets
- derive `item_input` from nested skill mappings
- enable aggregated named outputs when the graph references loop outputs like
  `normalize_all.normalized`
- rewrite stale `mapped -> results` references

These actions are surfaced through `PlanResult.repair_actions` and execution
result `runtime_repairs`.

### 2. Runtime retry for narrow graph failures

`run_glue_graph()` now:
- normalizes the graph before validation/execution
- executes once
- if execution fails on a known repairable graph contract issue, patches the
  graph once and retries

Current runtime-only retry rules:
- `mapped -> results`
- `result -> results`
- `array -> items` for collection ops

### 3. `parallel.map` can expose aggregated named outputs

`parallel.map` now supports `aggregate_outputs`.

That means a loop body returning:

```json
{"normalized": "hello"}
```

can expose both:
- `results = [{"normalized": "hello"}]`
- `normalized = ["hello"]`

This keeps the loop boundary visible while making direct output references
usable for plans that ask for named collected values.

### 4. `plan-and-run` now uses the real execution provider

The CLI previously used the live provider for planning but dropped it before
execution unless `--mock-llm` was set. That meant any retrieved LLM-backed
skill could plan successfully and then fail during execution.

`plan-and-run` now creates the same provider for execution, so live planning and
live execution are aligned.

## Validation

Regression:

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
- `202 passed`

## Live crowded-registry checks

Registry:
- published all 15 example skills into a temp local registry

Provider:
- Anthropic `claude-sonnet-4-20250514`

### Successful live paths

1. Multi-stage deterministic composition
- goal: normalize -> title-case -> count
- result: success
- output: titled text plus count

2. Branch-style execution
- goal: conditionally title-case or normalize
- result: success

3. Complex multi-stage composition with LLM-backed skill
- goal: clean text, extract topics, add header
- result: success
- important because this specifically verified the CLI execution-provider fix

4. Loop-style plan
- goal: normalize each string in a list
- result: now executes end to end instead of failing at graph/runtime contract

### Current remaining boundary

The loop path still has a contract-fidelity issue:
- the live run returned a collection under `mapped` instead of the requested
  `normalized`

That is a better failure mode than before:
- retrieval is not the problem
- loop execution is not the problem
- graph/runtime contract normalization is mostly working
- the remaining weakness is output-contract fidelity for loop plans

### Crowded-registry evaluation

`eval-planner` on `evaluation/challenge_goals` with the 15-skill registry:
- `11/12` pass
- `avg_candidates = 3.9`

The remaining miss is no longer a retrieval collapse. Retrieval stayed targeted
under distractor pressure.

## Takeaway

The system now has a meaningful “repair without replanning” path:
- patch local IR mistakes
- normalize graph contracts
- retry one narrow runtime fix

That moves the main boundary away from raw executability and toward semantic
fidelity:
- especially loop output naming and broader output-contract alignment

## Next step

The next high-value slice is output-contract repair:
- detect when execution produced the right structure under the wrong exposed
  port names
- patch final output mappings locally
- extend this first for loop outputs, then for broader multi-output plans
