# Sprint 42 — Trace Summaries and Promotion Inspection

## Scope
- Make stored traces easier to scan from the CLI
- Make promotion candidates easier to inspect before manual promotion
- Document the intended human workflow

## Why this sprint

Graphsmith already stores traces and mines repeated op-sequence patterns,
but the CLI ergonomics were still a little raw. This sprint improves the
inspection loop without changing the promotion heuristic itself.

## Changes

### Trace summaries
- Added `TraceStore.list_summaries()`
- Enriched per-trace summaries with:
  - `started_at`
  - `input_keys`
  - existing signature, outputs, status, duration

### CLI trace listing
- `graphsmith traces-list --summary` now prints one compact line per trace
- This makes it much easier to scan the trace store before drilling into
  a specific run

### Promotion candidate output
- `graphsmith promote-candidates` now shows example supporting traces
- Each example includes:
  - trace ID
  - skill ID
  - status
  - node count

### User-facing docs
- `docs/TRACES_AND_PROMOTION.md` now explains the intended human loop:
  execute -> inspect traces -> mine candidates -> inspect examples ->
  decide manually whether to promote

## Why this scope is narrow

This sprint does not change:
- promotion grouping heuristic
- automatic promotion behavior
- registry publication
- planner/runtime behavior

It only makes the existing trace-to-promotion workflow easier to use.

## Validation
- Added tests for:
  - `traces-list --summary`
  - promotion text output showing example traces
  - trace summaries including `started_at` and `input_keys`
  - `TraceStore.list_summaries()`
- Python compile check run locally

## What remains unchanged
- Promotion is still advisory only
- Matching is still top-level op-sequence only
- No config or edge-aware fragment mining yet
