# Planning IR Architecture

## Motivation

Direct LLM graph emission (the existing planner path) requires the LLM to produce
exact graph serialization: node IDs, edge addresses (`from`/`to` with `scope.port`
syntax), `graph_outputs` mapping, and config embedding. This creates a class of
failures that are mechanical rather than semantic:

- Self-loops (`format.prefix → format.prefix`)
- Invalid edge addresses (`config.X`, bare words, `output.X`)
- Constants as graph inputs instead of config
- Over-composition (adding formatting nodes when not requested)

These problems have diminishing returns when addressed via prompt engineering alone.
The IR architecture separates **what** (LLM semantic planning) from **how**
(deterministic graph construction).

## Pipeline

```
retrieve candidates → LLM emits IR → parse IR → compile IR → GlueGraph → validate → execute
                                                    ↑
                                          deterministic compiler
```

The existing direct path remains available:

```
retrieve candidates → LLM emits graph JSON → parse → validate → execute
```

## Components

### Planning IR (`graphsmith/planner/ir.py`)

Semantic intermediate representation. The LLM emits this instead of raw graph JSON.

```python
PlanningIR:
  goal: str
  inputs: list[IRInput]          # graph-level inputs (name, type)
  steps: list[IRStep]            # ordered skill/op invocations
  final_outputs: dict[str, IROutputRef]  # what the user gets back
  effects: list[str]
  reasoning: str

IRStep:
  name: str                      # human-readable step name
  skill_id: str                  # skill ID or primitive op name
  version: str
  sources: dict[str, IRSource]   # input_port → where data comes from
  config: dict[str, Any]         # static config (template strings, etc.)

IRSource:
  step: str                      # "input" for graph inputs, or step name
  port: str                      # output port name
```

The IR is deliberately smaller than the graph format:
- No edge addresses (just step name + port)
- No node IDs (step names become node IDs)
- No `graph_outputs` mapping (derived from `final_outputs`)
- No `op` field (derived from `skill_id` — primitive ops use skill_id directly)

### Deterministic Compiler (`graphsmith/planner/compiler.py`)

`compile_ir(ir: PlanningIR) → GlueGraph`

Phases:
1. **Validate IR** — check references, effects, cycles, self-loops
2. **Build nodes** — map steps to `GraphNode` objects, resolve op vs skill.invoke
3. **Build edges** — map sources to `GraphEdge` objects with proper `scope.port` syntax
4. **Build outputs** — map `final_outputs` to `graph_outputs` dict
5. **Assemble** — create `GlueGraph` with `GraphBody`

### Structured Compiler Errors

All errors inherit from `CompilerError(phase, details)`:

| Error | Meaning |
|-------|---------|
| `EmptyStepsError` | IR has no steps |
| `DuplicateStepError` | Two steps share a name |
| `UnknownSourceStepError` | Source references non-existent step |
| `UnknownOutputStepError` | Final output references non-existent step |
| `UnknownInputError` | Source references undeclared graph input |
| `InvalidEffectError` | Effect not in allowed set |
| `SelfLoopError` | Step sources from itself |
| `CycleError` | Step dependencies form a cycle |

Each error carries `phase` and `details` so the planner can classify
where a failure happened and, for some block-local issues, attempt a
deterministic repair.

### IR Prompt (`graphsmith/planner/ir_prompt.py`)

Simpler prompt than `prompt.py` because the LLM only needs to express:
- What steps to take
- Where each step gets its data
- What to expose as final outputs

Same rules (composition policy, constants, output naming) apply.

### IR Parser (`graphsmith/planner/ir_parser.py`)

Parses raw LLM text into `PlanningIR`. Reuses `_extract_json_text()` from the
existing parser for code fence / balanced brace extraction.

### IR Backend (`graphsmith/planner/ir_backend.py`)

`IRPlannerBackend` implements the `PlannerBackend` protocol:
1. Build IR prompt from `PlanRequest`
2. Call LLM provider
3. Parse response into `PlanningIR`
4. Compile IR into `GlueGraph`
5. Return `PlanResult`

Drop-in replacement for `LLMPlannerBackend` — same interface, different pipeline.

## What stays unchanged

- `GlueGraph`, `PlanResult`, `PlanRequest` models
- `glue_to_skill_package()`, `validate_skill_package()`
- Runtime execution (`run_glue_graph()`, `run_skill_package()`)
- `compose_plan()` orchestrator (works with any `PlannerBackend`)
- Evaluation harness
- All existing tests

## Deterministic local repair

Graphsmith now includes a bounded multi-layer repair path:
- IR-local repair before final compiler failure
- block-local LLM regeneration when a single branch/loop block is still invalid
- graph-level contract normalization before validation/execution
- one runtime-informed graph patch retry on specific execution failures
- one runtime-trace-guided branch/loop region regeneration retry

### 1. IR-local repair

This runs between IR parsing and final compiler failure.

Current scope:
- branch blocks with missing or incomplete `then_outputs` / `else_outputs`
- loop blocks with missing `final_outputs`
- loop blocks with exactly one body input but no explicit `$item` binding
- `array.map` operations emitted as bound sources instead of config

Repair is intentionally bounded:
- no extra LLM call
- no whole-plan regeneration
- only patch the failing block
- only when the missing contract can be inferred from surrounding references

Examples:
- if a top-level output references `format_branch.rendered` and the branch arms
  omit output declarations, the repair pass can map `rendered` to the terminal
  step of each arm
- if a loop block is referenced as `normalize_each.normalized` and its body ends
  in `normalize`, the repair pass can infer `final_outputs.normalized =
  normalize.normalized`

### 2. Graph contract normalization

This runs on the compiled `GlueGraph` before validation and again before
execution of saved plans.

Current scope:
- rewrite legacy `array.map` / `parallel.map` input alias `array -> items`
- lift `parallel.map` shorthand like `operation: "text.normalize"` into
  runtime config
- flatten nested `parallel.map` `skill.invoke` targets emitted as objects
- enable aggregated named loop outputs when the graph references
  `parallel.map.<field>` rather than only `parallel.map.results`
- rewrite stale loop output alias `mapped -> results`
- align generic collection outputs like `results` / `mapped` to a named loop
  output when the inner op contract makes that mapping deterministic
- infer single-output loop result names from fetched skill contracts when the
  loop body is `skill.invoke`

This matters because saved plans and direct graph output can still contain
legacy or partially-normalized loop contracts even when the semantic plan is
basically correct.

### 3. Runtime-informed patch retry

This is still intentionally narrow: one retry after a specific runtime failure.

Current scope:
- rewrite stale `mapped -> results` references when execution proves only
  `results` exists
- rewrite stale `result -> results` references for collection outputs
- rewrite runtime input alias failures like `array.map` / `parallel.map`
  expecting `items`
- enable aggregated named loop outputs when runtime proves the graph requested a
  specific loop field but only `results` was materialized and the loop body
  contract makes that field deterministic

This is not yet a general repair loop. It still does not:
- fix arbitrary bad dataflow
- synthesize entirely new missing capabilities
- recover from unknown skills or broad type mismatches
- classify and patch arbitrary regions from full traces
- guarantee user-intended output naming in the general case when the plan is
  semantically close but the naming ambiguity is not deterministic

### 4. Block-local regeneration

When deterministic IR-local repair is not enough and the compiler error is
still scoped to a single `branch` or `loop` block, Graphsmith now performs one
bounded LLM retry against just that block.

Current behavior:
- preserve the surrounding IR unchanged
- preserve the failing block's `name` and `kind`
- pass the goal, compiler error, current block JSON, graph inputs, top-level
  step names, available skills, and required exposed output names into a repair
  prompt
- require the model to return only `{"block": {...}}`
- splice the repaired block back into the original IR and retry compilation once

This matters because it keeps the "zoom into one region and patch it" property
without falling back to whole-plan regeneration.

Current limitations:
- only one retry
- only for block-local compiler failures that still carry a `block_name`
- no nested-region regeneration
- no skill synthesis if the repaired block still lacks capability

### 5. Runtime-trace-guided region regeneration

When execution reaches a lowered control-flow region and fails at runtime,
Graphsmith now performs one additional bounded repair layer using the observed
trace.

Current behavior:
- lowered loop and branch regions now carry source block metadata in node config
- `parallel.map` now propagates failed child traces outward, including inline
  loop body failures
- executor-raised `ExecutionError`s now carry the run trace and failing node id
- `run_glue_graph()` first tries deterministic runtime graph repair, then, if
  that is insufficient, it uses the failing runtime trace to regenerate only
  the affected loop or branch region
- the repaired region is re-lowered and spliced back into the existing graph,
  preserving the rest of the graph unchanged

This is the first runtime repair layer that uses structural evidence instead of
only error-string pattern matching.

Current limitations:
- only one trace-guided regeneration attempt
- only top-level lowered `loop` and `branch` regions
- branch support exists structurally, but current tests cover the loop path
- region replacement assumes the block preserves its exposed outputs
- no nested region repair from deep child traces yet
- no skill synthesis fallback if region regeneration still fails

## Output-contract repair

Graphsmith now has a first bounded output-contract repair layer for loop-style
plans.

Current scope:
- if a `parallel.map` wraps a single-output inner op and the outer graph exposes
  a generic collection alias like `results` or `mapped`, the graph can rewrite
  that to the named collected output (for example `normalized`)
- if the graph already uses the right output name but still points at the
  generic collection port, the graph can rewrite the final output address to the
  named collected output

This is intentionally narrow and structural:
- it does not guess from the user prompt
- it does not rename arbitrary unrelated outputs
- it only fires when the inner loop body contract makes the mapping clear

## Future: structural repair loop

The next layer is a fuller structural repair loop:
- classify compiler and runtime failures by region and failure type
- patch nested regions, not just top-level blocks
- repair a single branch arm instead of regenerating the whole branch block
- escalate from local repair to skill synthesis only when local composition
  remains insufficient
