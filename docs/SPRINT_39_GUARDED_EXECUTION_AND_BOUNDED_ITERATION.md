# Sprint 39 — Guarded Execution and Bounded Iteration

## Summary

This sprint extends Graphsmith past pure pipeline DAG composition in two concrete ways:

1. **Graph-level guarded execution**
   Nodes can now execute conditionally via `when`, with deterministic skip semantics.

2. **Bounded iteration over reusable skills**
   `parallel.map` can now invoke `skill.invoke` per item, not only pure primitive ops.

These changes keep the current deterministic runtime model intact while adding the first real control-flow and iteration semantics that compose with reusable skills.

## Why this matters

The next version of Graphsmith should be easy for an LLM to inspect at multiple levels:
- the whole plan,
- a branch or loop region,
- a specific step,
- the skill behind a step.

Guarded execution and bounded iteration are the first runtime features that make that practical without collapsing back into raw code generation.

## What changed

### 1. Guarded execution

`GraphNode.when` was already present in the model, but had no runtime behavior.
It now supports:

- `when: "input.flag"` → execute only if truthy
- `when: "node.port"` → execute only if upstream value is truthy
- `when: "!input.flag"` → execute only if falsy

Runtime behavior:
- skipped nodes are recorded in traces with `status="skipped"`
- guarded dependencies participate in topological ordering
- guarded dependencies participate in DAG validation
- inputs referenced only by conditions count as real graph dependencies
- downstream nodes can safely consume maybe-missing values from skipped branches

This gives Graphsmith executable branch behavior at the graph level instead of only value-level selection through `branch.if`.

### 2. IR support for guarded steps

Planning IR steps now support:
- `when: IRSource`
- `unless: bool`

The compiler lowers these into graph-level `when` addresses:
- `when=input.enabled` for normal guards
- `when=!input.skip` for negated guards

This keeps conditional execution representable at the IR layer rather than requiring direct graph editing.

### 3. Bounded iteration via `parallel.map`

`parallel.map` previously supported only pure primitive ops and explicitly rejected `skill.invoke`.

It now supports:
- primitive inner ops
- `skill.invoke` as the inner body
- `item_input` to map each item into a named inner input port
- passthrough of outer inputs to each inner invocation
- `max_items` hard bounds for deterministic, bounded iteration

Example:

```yaml
nodes:
  - id: map
    op: parallel.map
    config:
      op: skill.invoke
      item_input: text
      max_items: 10
      op_config:
        skill_id: text.normalize.v1
        version: 1.0.0
```

This enables “run this reusable skill for each item” without introducing general loop blocks into the compiler yet.

## Validation and runtime rules

### New validation behavior

- invalid `when` references fail validation
- `when` references to unknown inputs or nodes fail validation
- cycles introduced through condition dependencies are rejected
- required graph inputs consumed only by conditions are treated as wired

### New runtime behavior

- skipped nodes do not execute
- skipped branches do not write outputs
- downstream bindings sourced from skipped nodes are omitted instead of forcing immediate failure
- bounded iteration fails fast if item count exceeds `max_items`

## Tests added

### Guarded execution
- IR parse/compile tests for `when` and `unless`
- validator tests for invalid `when` references
- validator cycle detection through condition dependencies
- runtime tests for true/false branch execution
- runtime tests for skipped node traces
- topological ordering tests where `when` creates a dependency

### Bounded iteration
- `parallel.map` tests for `skill.invoke`
- passthrough input tests
- `item_input` remapping tests
- `max_items` enforcement tests
- runtime end-to-end execution of `parallel.map` invoking a real published skill

## Limits that remain

This sprint does **not** yet implement:
- lowering of `IRBlock(kind="branch")`
- lowering of `IRBlock(kind="loop")`
- graph-level merge semantics beyond existing node wiring
- effect-aware scheduling
- mutable state or transactional semantics
- general recursion

So this is still not a general programming language. But it is now a better substrate for one:
- conditional execution is real
- iteration over reusable subgraphs is real
- both remain bounded, typed, deterministic, and inspectable

## Verification

Validated locally with:

```bash
.venv/bin/pytest tests/test_parallel_map.py tests/test_runtime.py tests/test_validator.py tests/test_planning_ir.py -q
.venv/bin/pytest tests/test_ir_hardening.py tests/test_llm_type_failures.py tests/test_ir_semantic_fidelity.py tests/test_final_failure_analysis.py -q
```

## Next step

The next logical step is **first-class loop/block lowering**:
- represent loop bodies structurally in IR
- compile them into bounded executable regions
- preserve zoom-in / zoom-out inspectability for both the planner and the UI
