# Sprint 40 — Retrieval Visibility and Contract Scoring

## Scope
- Make retrieval diagnostics visible during normal planning
- Improve ranked retrieval using skill contract metadata

## Why this sprint

The planner can only compose from the shortlist it sees. When the right
skill is absent, planner quality no longer reflects planner quality —
it reflects retrieval quality. This sprint improves observability first
and retrieval scoring second.

## Changes

### Retrieval diagnostics in normal planning
- `compose_plan` now retains retrieval diagnostics on `PlanResult`
- `graphsmith plan --show-retrieval` prints:
  - retrieval mode
  - raw tokens
  - expanded tokens
  - shortlisted skills with scores

### Contract-aware ranked scoring
- Ranked retrieval now scores more than name/description/tags
- Additional signal sources:
  - input names
  - output names
  - effects
- Output-name matches are weighted most strongly

## Why this scope is narrow

This sprint does not change:
- planner prompts
- IR generation
- compiler behavior
- validation
- execution
- registry format

It only makes retrieval more inspectable and slightly more semantic.

## Validation
- Added tests for:
  - retrieval attached to normal `compose_plan` results
  - `--show-retrieval` in CLI text output
  - contract-field scoring for input/output names
- Python compile check run locally

## What remains unchanged
- Retrieval modes
- Candidate reranking
- Closed-loop generation
- UI behavior
- Release process
