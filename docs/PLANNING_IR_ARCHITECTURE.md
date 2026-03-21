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

Each error carries `phase` and `details` for future repair loop support.

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

## Future: repair loop

The structured `CompilerError` types (with `phase` and `details`) are designed
to support a future repair loop where compiler errors are fed back to the LLM
for correction. This is NOT implemented yet — this sprint builds the clean
foundation first.
