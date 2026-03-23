# Sprint 41 — Benchmark and Release Hardening

## Scope
- Define one canonical planner eval path
- Add one small smoke script for core CLI commands
- Tighten release docs around those exact commands

## Why this sprint

After Sprint 40, retrieval is easier to inspect during planning. The
next need is a cheap, repeatable way to catch regressions before a
release. The goal here is not broader infrastructure; it is a clearer
"ready to ship" path.

## Changes

### Canonical eval
- Added `scripts/eval_canonical.sh`
- Uses:
  - `evaluation/goals`
  - `--backend ir`
  - `--ir-candidates 3`
  - `--decompose`
- This becomes the default planner regression check

### Release smoke script
- Added `scripts/release_smoke.sh`
- Covers:
  - `plan`
  - `plan --show-retrieval`
  - `plan-and-run`
  - `ui --help`
- Intentionally offline and small

### Docs tightened
- `docs/RELEASE_CHECKLIST.md` now points to the smoke script and
  canonical eval command
- `docs/RUNNING_EVALS.md` now leads with the canonical benchmark path

## Why this scope is narrow

This sprint does not change:
- planner behavior
- retrieval scoring
- compiler/runtime
- UI implementation
- eval datasets

It only makes release checks and regression checks more explicit.

## Validation
- Added executable scripts for the two new release paths
- Python compile check run locally

## What remains unchanged
- Full three-set eval workflow
- Stability evaluation
- Live campaign tooling
- Release tagging flow
