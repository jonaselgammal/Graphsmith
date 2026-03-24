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
- graph-level contract normalization before validation/execution
- one runtime-informed graph patch retry on specific execution failures

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

This is not yet a general repair loop. It still does not:
- fix arbitrary bad dataflow
- synthesize missing branch or loop bodies
- recover from unknown skills or broad type mismatches
- classify and patch arbitrary regions from full traces
- guarantee user-intended output naming when the plan is semantically close but
  contract fidelity is weak

## Future: structural repair loop

The next layer is a real structural repair loop:
- classify compiler/runtime failures by region
- patch one branch or loop body instead of replanning the whole graph
- optionally use LLM-guided edits when deterministic repair is insufficient
- feed trace evidence back into repair decisions
