# Sprint 50: Local Subgraph Regeneration

## Goal

Add the next repair layer after deterministic block repair: regenerate only a
single failing branch or loop block while preserving the rest of the IR.

## What changed

- Added block-only repair prompting in
  `graphsmith/planner/ir_prompt.py`.
- Added block-only parsing in `graphsmith/planner/ir_parser.py` via
  `parse_ir_block_output()`.
- Extended `IRPlannerBackend` in `graphsmith/planner/ir_backend.py` with a
  bounded local regeneration path:
  - normalize IR contracts
  - try deterministic compile
  - try deterministic local repair
  - if a branch/loop block still fails with a block-local compiler error,
    regenerate just that block with one LLM call
  - splice the repaired block back into the IR
  - retry compilation once
- Exported `infer_block_output_ports()` from
  `graphsmith/planner/repair.py` so the repair prompt can preserve the block's
  required external contract.

## Why this matters

This is the first repair layer that is genuinely structural without reverting
to full-plan regeneration.

The planner can now:
- keep the global graph shape stable
- zoom into one invalid control-flow region
- regenerate only that region
- preserve the external interface the rest of the plan already depends on

That is directly aligned with the longer-term Graphsmith goal of making plans
easy for an LLM to inspect and locally rewrite.

## Boundaries

This is intentionally narrow:
- only one regeneration attempt
- only branch and loop blocks
- only compiler failures that still identify a `block_name`
- no runtime-trace-guided regeneration yet
- no nested block regeneration
- no automatic skill synthesis fallback yet

## Tests

Added backend regressions that prove:
- an invalid loop block can be regenerated locally while preserving a valid
  top-level step outside the block
- an invalid branch block can be regenerated locally and lower to the guarded
  branch merge form

Validation:

```bash
conda run -n graphsmith pytest tests/test_planning_ir.py -q
conda run -n graphsmith pytest tests/test_plan_execution.py tests/test_parallel_map.py -q
conda run -n graphsmith pytest tests/test_runtime.py tests/test_cli.py -q
conda run -n graphsmith pytest tests/test_planner_parser.py tests/test_registry.py tests/test_retrieval_diagnostics.py -q
conda run -n graphsmith python -m compileall graphsmith
```

## Next

The next useful layer is runtime-trace-guided region regeneration:
- identify which loop body or branch arm actually failed at execution time
- regenerate that region using the observed trace and runtime error
- preserve the rest of the compiled plan
