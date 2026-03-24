# Sprint 40 — Loop Block Lowering

## Summary

This sprint makes the first structured control-flow block executable in the planning IR:

- `IRBlock(kind="loop")` is now supported
- loop blocks are lowered deterministically into a visible `parallel.map` node
- the loop body is preserved as an inline executable subgraph
- iteration results can be exposed by named output port, not only as opaque `results`

This is the first step where iteration becomes a planner-native structure instead of only an op-level helper.

## Why this matters

The long-term goal is not just “more powerful graphs”, but graphs that remain easy for an LLM to:
- understand globally,
- zoom into locally,
- modify partially,
- and recompose without regenerating everything.

Before this sprint, `parallel.map` existed, but loops were not structural in the IR.
Now the planner can represent a loop body as a proper region with inputs, steps, and outputs.

## What changed

### 1. `IRBlock(kind="loop")` is executable

`IRBlock` now supports:
- `collection: IRSource`
- `inputs: dict[str, IRSource]`
- `steps`
- `final_outputs`
- `max_items`

Loop semantics:
- `collection` identifies the array to iterate over
- `inputs` define the loop body input bindings
- `{"binding": "item"}` or `"$item"` marks body inputs that receive the current item
- other input bindings are passed through from outer scope

### 2. Deterministic lowering to `parallel.map`

The compiler now lowers loop blocks into a single top-level node:

- `op: parallel.map`
- `config.mode: "inline_graph"`
- `config.body`: inline compiled body graph
- `config.item_inputs`: body input names receiving the current item
- `config.max_items`: explicit bound

This preserves a visible loop boundary in the graph while still using the existing deterministic runtime kernel.

### 3. Inline loop body execution

`parallel.map` now supports an inline body mode:
- compiles and executes a synthetic in-memory skill package per item
- supports both item-derived inputs and outer passthrough inputs
- returns:
  - `results`: list of per-item output dicts
  - one collected output array per named body final output

Example:

```json
{
  "name": "normalize_each",
  "kind": "loop",
  "collection": "input.items",
  "inputs": {
    "text": "$item"
  },
  "steps": [
    {
      "name": "normalize",
      "skill_id": "text.normalize.v1",
      "sources": {"text": "input.text"}
    }
  ],
  "final_outputs": {
    "normalized": "normalize.normalized"
  },
  "max_items": 10
}
```

The top-level plan can then reference:
- `normalize_each.results`
- `normalize_each.normalized`

### 4. Iteration traces

For compiler-lowered loop blocks, `parallel.map` records a child trace:
- one synthetic node per item (`item_0`, `item_1`, ...)
- each item may itself contain a nested child trace for the inline body

This keeps the loop body inspectable after execution rather than collapsing it into one opaque node.

## Validation and constraints

Loop lowering is intentionally bounded:
- loop blocks must declare `collection`
- loop blocks must declare at least one `final_output`
- loop blocks must bind at least one body input to the loop item
- `max_items` must be non-negative

What is still unsupported:
- `IRBlock(kind="branch")`
- `IRBlock(kind="function")`
- nested loop blocks with special lowering behavior beyond recursive compilation
- index-aware loops
- break/continue semantics
- reductions/folds as first-class blocks

## Tests added

- compiler lowering for loop blocks
- compiler rejection when `collection` is missing
- parser support for loop block `collection`
- runtime execution of loop blocks with collected named outputs
- runtime execution of loop blocks using outer passthrough inputs

## Verification

Validated locally with:

```bash
.venv/bin/pytest tests/test_parallel_map.py tests/test_planning_ir.py tests/test_runtime.py tests/test_validator.py tests/test_ir_hardening.py tests/test_llm_type_failures.py tests/test_ir_semantic_fidelity.py tests/test_final_failure_analysis.py -q
.venv/bin/python -m compileall graphsmith
```

## Next step

The next logical step is **branch block lowering**:
- make `IRBlock(kind="branch")` executable
- preserve explicit branch regions in the IR and traces
- allow local re-planning and repair of one branch without rebuilding the whole plan
