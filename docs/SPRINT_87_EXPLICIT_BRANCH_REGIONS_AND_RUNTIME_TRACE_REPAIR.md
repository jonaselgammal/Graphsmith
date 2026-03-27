# Sprint 87: Explicit Branch Regions And Runtime Trace Repair

This sprint closes a real architecture gap between execution and repair.

Graphsmith already had branch-region repair logic at the graph level, but two things were preventing it from helping the new coding-style environment workflows:

- the pytest prefix branch fallback was still hand-built as a plain graph instead of an explicit IR branch block
- runtime failures during input binding resolution were not recorded as node-level error traces, so region repair had nothing concrete to target

## What changed

- `graphsmith/skills/closed_loop.py`
  - rewrote the pytest status-prefix environment fallback as an explicit `IRBlock(kind="branch")`
  - this means the resulting graph now carries normal branch-region metadata instead of an ad hoc hand-built branch shape

- `graphsmith/runtime/executor.py`
  - input-binding resolution failures now append an error `NodeTrace` for the failing node before re-raising
  - that makes region-level runtime repair possible even when the failure happens before op execution

- `graphsmith/planner/graph_repair.py`
  - fixed branch-region replacement to recognize the current lowered branch naming pattern (`block_then_*`, `block_else_*`, `block_merge_*`) in addition to the older legacy pattern

- `tests/test_plan_execution.py`
  - added a regression proving that an explicit branch region can fail at runtime and be regenerated from trace evidence

- `tests/test_runtime.py`
  - added a regression proving that binding-resolution failures create an error trace node instead of disappearing into a generic execution error

## Why this matters

This is a structural repair improvement, not a benchmark patch.

After this sprint:

- environment branches are represented as real regions
- runtime trace repair can patch those regions even when the failure is in address resolution
- the execution substrate is closer to “compiler + runtime + local program repair” instead of just “graph executor with retries”

That is a necessary step if Graphsmith is going to handle broader programming tasks where failures often happen at the boundaries between regions, inputs, and effectful steps.

## Verification

- `conda run -n graphsmith pytest tests/test_plan_execution.py tests/test_closed_loop.py tests/test_runtime.py -q`
- `105 passed`
- `conda run -n graphsmith python -m compileall graphsmith`

## Evaluation spot check

Old suite sanity check with Groq Llama against the hosted remote registry:

- `evaluation/goals`: `6/9`

That is in line with the current planner/provider variance and did not show a catastrophic regression from the new region-repair work.
