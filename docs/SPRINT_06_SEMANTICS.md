# Sprint 06 Semantics

## parallel.map — sequential fallback with parallel interface

`parallel.map` applies an inner op to each item of an input array.
In v1, execution is **strictly sequential** — items are processed
one at a time in order. The "parallel" name reflects the interface
contract, not the execution model.

### Supported form: inner primitive op

Config:
- `op` (str, required): the primitive op to apply per item (e.g. `template.render`)
- `op_config` (dict, optional): static config passed to the inner op for each item

Inputs:
- `items` (list): the source array

Per-item execution:
- each item is passed as `{"item": <value>}` to the inner op
- the inner op receives `(op_config, {"item": item})`

Output port: `results` — a list of inner op outputs (the full dict each time)

### Not supported in v1
- `skill.invoke` per item (requires registry threading — deferred)
- nested parallel.map
- real concurrency

Unsupported forms fail with a clear OpError.

## Trace summary semantics

`traces-show --summary` prints a compact human-readable summary:
- skill_id
- status
- duration (ended_at - started_at, if both present)
- node count
- child trace count (from skill.invoke nodes)
- op sequence signature
- output keys

This is a read-only view — no computation beyond what's in the trace file.

## Trace pruning semantics

`traces prune --older-than <days>` removes trace files whose
`started_at` timestamp is older than `now - days`.

- Only files parseable as traces with a valid `started_at` are candidates
- Unparseable files are left untouched
- Returns count of removed traces
- Deterministic: same inputs → same removals
- `--dry-run` shows what would be removed without deleting

## Minimal real planner backend interface

`LLMPlannerBackend` is a concrete class that:
1. Receives a `PlanRequest`
2. Builds a prompt via `build_planning_context()`
3. Sends the prompt to an injected `LLMProvider`
4. Parses the LLM response into a `PlanResult`

In v1, this class exists but parsing LLM output is a stub that
returns a failure result with a "parsing not yet implemented" note.
The interface is ready for a real integration without changing the
planner core.

## End-to-end integration test coverage

The integration test exercises this full local workflow:
1. Publish example skills to a temp registry
2. Plan a glue graph using the mock planner
3. Run the planned skill (via skill.invoke) with mock LLM
4. Persist the trace
5. Load and inspect the trace
6. Run promotion candidate generation

All steps use temp directories, mock providers, and no network.

## Explicit limitations

- parallel.map is sequential only
- parallel.map supports only inner primitive ops, not skill.invoke
- trace pruning uses started_at from the JSON content, not filesystem mtime
- LLMPlannerBackend exists but cannot parse real LLM output yet
- the integration test uses mock/echo backends throughout
- no true concurrency anywhere in the system
