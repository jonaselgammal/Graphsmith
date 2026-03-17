# Sprint 07B — Plan Execution Semantics

## How glue graphs are represented for execution

A `GlueGraph` is internally converted to a synthetic `SkillPackage` via
`glue_to_skill_package()` before execution. This reuses the existing
executor without any changes to the runtime core.

The synthetic package has:
- `id`: `_glue.<slugified_goal>`
- `version`: `0.0.0`
- `root_path`: `(generated)`

This conversion is an internal detail. Externally, glue graphs are
always represented as `GlueGraph` objects (typed, not disguised).

## Validation before running

Before any glue graph execution:
1. Convert to synthetic `SkillPackage`
2. Run through `validate_skill_package()`
3. If validation fails, do not execute — return structured error

Partial or failed `PlanResult`s are never executed.

## Saved plan format

Plans are saved as JSON using `GlueGraph.model_dump()` directly.
The file is a first-class GlueGraph, **not** a synthetic skill package.

```json
{
  "goal": "summarize text",
  "inputs": [{"name": "text", "type": "string", "required": true}],
  "outputs": [{"name": "summary", "type": "string", "required": true}],
  "effects": ["llm_inference"],
  "graph": {
    "version": 1,
    "nodes": [...],
    "edges": [...],
    "outputs": {...}
  }
}
```

Loading a saved plan reconstructs a `GlueGraph` via `GlueGraph.model_validate()`.

## `plan-and-run` vs `run-plan`

| Command | Input | Planning | Execution |
|---------|-------|----------|-----------|
| `plan-and-run` | goal string | yes (live) | yes (immediate) |
| `run-plan` | saved plan JSON file | no | yes |

### `plan-and-run "<goal>"`
1. Retrieve candidates from registry
2. Compose plan via selected backend
3. Validate the planned graph
4. If success: execute, return outputs
5. If partial/failure: display holes, exit non-zero, do not execute

### `run-plan <path>`
1. Load and parse saved plan JSON into `GlueGraph`
2. Validate
3. Execute with provided inputs
4. Return outputs

## What inputs a glue graph execution expects

The glue graph's `inputs` field declares the required input ports.
At execution time, the user provides values for these ports via
`--input` or `--input-file`, same as `graphsmith run`.

## Trace behavior

Executed glue graphs produce traces identically to skill runs.
- `skill_id` in the trace is `_glue.<slugified_goal>`
- Nested `skill.invoke` child traces are preserved
- Traces can be persisted via `--trace-root`

The `_glue.` prefix makes it easy to distinguish plan-derived
executions from published skill executions in trace listings.

## Explicit limitations

- Only `success` plans are executed; partial/failure plans are not
- No planner self-repair loop (plan fails → stop)
- Saved plans are not publishable as skills
- No plan versioning — plans are ephemeral artifacts
- No plan diffing or comparison tooling
