# Sprint 51: Runtime Trace-Guided Region Repair

## Goal

Extend local subgraph regeneration from compile-time block failures to runtime
failures inside lowered loop/branch regions.

## What changed

- `ExecutionError` in `graphsmith/exceptions.py` now carries the failing
  `trace` and `node_id`.
- `parallel.map` in `graphsmith/ops/parallel_map.py` now propagates failed
  child traces even when the inline loop body fails before its first node runs.
- `run_skill_package()` in `graphsmith/runtime/executor.py` now attaches child
  traces to error nodes and preserves the full run trace on failure.
- Lowered control-flow regions in `graphsmith/planner/compiler.py` now carry
  source block metadata in node config:
  - loop nodes store the original loop block
  - branch side and merge nodes store the original branch block
- `graphsmith/planner/graph_repair.py` now includes
  `repair_glue_graph_from_runtime_trace()`:
  - identify the failing lowered node from the runtime trace
  - recover the original source block from node metadata
  - prompt the model with the runtime error plus trace summary
  - parse a repaired `{"block": {...}}`
  - re-lower just that region
  - splice the repaired region back into the existing `GlueGraph`
- `run_glue_graph()` in `graphsmith/planner/composer.py` now uses that repair
  path after deterministic runtime repair is exhausted.

## Why this matters

This is the first repair slice that uses real execution evidence to patch a
control-flow region while keeping the rest of the graph fixed.

That is important for the larger Graphsmith goal because it means:
- the planner does not need to restart from scratch after a local runtime error
- loops and branches become repairable units
- the graph keeps its inspectable global shape while local regions evolve

## Test coverage

Added a focused runtime execution regression in
`tests/test_plan_execution.py` that proves:
- a lowered loop region can fail at runtime
- the runtime trace identifies the failing region
- the region is regenerated locally
- execution succeeds on the retried graph

Validation:

```bash
conda run -n graphsmith pytest tests/test_plan_execution.py tests/test_runtime.py tests/test_planning_ir.py -q
conda run -n graphsmith pytest tests/test_cli.py tests/test_parallel_map.py tests/test_planner_parser.py tests/test_registry.py tests/test_retrieval_diagnostics.py -q
conda run -n graphsmith pytest tests/test_plan_execution.py tests/test_runtime.py tests/test_planning_ir.py tests/test_ir_hardening.py tests/test_llm_type_failures.py tests/test_ir_semantic_fidelity.py -q
conda run -n graphsmith python -m compileall graphsmith
```

## Boundaries

This is still intentionally narrow:
- only one trace-guided retry
- only top-level lowered loop/branch regions
- no nested region repair yet
- no per-branch-arm repair yet
- no skill synthesis fallback yet

## Next

The next major layer should be auto skill generation and promotion:
- synthesize missing capabilities only after local composition and repair fail
- evaluate whether synthesized skills should stay local or be promoted
- stress the system with harder, broader-domain tasks to establish the current
  generalization frontier
