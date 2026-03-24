# Sprint 41 — Branch Block Lowering

## Summary

This sprint makes the second structured control-flow block executable in the planning IR:

- `IRBlock(kind="branch")` is now supported
- branch blocks lower into guarded then/else subgraphs plus deterministic merge nodes
- downstream steps and final outputs can reference branch outputs like ordinary ports

Together with Sprint 40 loop lowering, this means the IR can now express both bounded iteration and structural branching without falling back to raw graph authoring.

## Why this matters

The main architectural goal is not only execution power but **multi-resolution inspectability**:
- whole-plan intent
- loop / branch regions
- individual steps
- skill contracts behind those steps

Before this sprint, branching existed only as:
- runtime guards on nodes
- value-level `branch.if`

That was enough to execute conditionals, but not enough to represent a branch as a planner-native region.

## What changed

### 1. `IRBlock(kind="branch")` is executable

Branch blocks now support:
- `condition: IRSource`
- `inputs: dict[str, IRSource]`
- `then_steps`
- `else_steps`
- `then_outputs`
- `else_outputs`

The `then_outputs` and `else_outputs` maps must declare the same output names.

### 2. Deterministic lowering strategy

Branch lowering compiles a branch block into:

1. guarded `then` steps
2. guarded `else` steps
3. one merge node per declared output

Lowering details:
- `then` steps get `when = condition`
- `else` steps get `when = !condition`
- merge nodes use `fallback.try`
  - `primary` = then branch output
  - `fallback` = else branch output

Because skipped nodes do not materialize outputs, the merge node deterministically selects the branch that actually ran.

### 3. Branch outputs become normal graph outputs

After lowering, references like:

```json
{"step": "format_branch", "port": "rendered"}
```

are rewritten to the merge node result, so:
- top-level `final_outputs` can target branch outputs
- later top-level steps can source from branch outputs
- branch regions remain composable with the rest of the graph

### 4. Block-local inputs and local rewiring

Branch body steps can use `input.<name>` for block-local inputs.
Those local inputs are rewritten deterministically from the block’s `inputs` mapping during lowering.

This preserves a local, readable branch body while still compiling into the flat executable graph model.

## Constraints

The current branch lowering is intentionally narrow:

- both `then_steps` and `else_steps` are required
- both `then_outputs` and `else_outputs` are required
- output keys must match exactly
- nested step-level `when` inside branch bodies is not supported yet
- `function` blocks remain unsupported

This keeps lowering deterministic and avoids ambiguous merge semantics.

## Tests added

### Focused branch tests
- parser support for branch blocks
- compiler lowering to guarded steps and merge nodes
- compiler failure for mismatched output contracts
- runtime execution of the `then` path
- runtime execution of the `else` path

### End-to-end verification

Validated in the `graphsmith` conda env with:

```bash
conda run -n graphsmith pytest tests/test_planning_ir.py tests/test_runtime.py -q
conda run -n graphsmith pytest tests/test_integration.py tests/test_plan_execution.py tests/test_cli.py -q
```

Also revalidated compilation with:

```bash
conda run -n graphsmith python -m compileall graphsmith
```

## What remains

Graphsmith now has:
- guarded execution
- bounded iteration over inline subgraphs
- structural branch regions lowered into executable graphs

But it still does not have:
- first-class reductions / folds
- function block lowering
- stateful block scopes
- branch-local repair / replan loops
- effect-aware scheduling / compensation semantics

## Next step

The next logical step is **structural repair and local re-planning**:
- compiler/runtime errors should point at a specific block or subgraph
- refinements should patch one branch or loop body instead of replanning the whole graph
- traces should support “zoom to failing region” workflows directly
