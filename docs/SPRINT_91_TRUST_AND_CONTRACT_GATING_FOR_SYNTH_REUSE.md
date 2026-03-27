# Sprint 91: Trust And Contract Gating For Synth Reuse

This sprint tightens when Graphsmith is allowed to reuse synthesized skills,
especially remote synthesized coding workflows.

## What Changed

- Added public helpers in `graphsmith/planner/policy.py` for published/trusted
  provenance checks.
- Added a conservative reuse gate in `graphsmith/skills/closed_loop.py`:
  - synthesized reuse now requires explicit structural tags:
    - `synthesized`
    - `subgraph`
    - `closed-loop`
    - `validated`
  - local synthesized skills remain reusable when the contract matches
  - remote synthesized skills are only reusable when they are trusted published
    entries with explicit provenance
  - effectful synthesized coding workflows additionally require explicit
    capability tags like `coding` and `environment`
- Synthesized skills now include `validated`, and smoke-tested ones also include
  `smoke_tested`.

## Tests

- Added closed-loop tests proving:
  - an untrusted remote synthesized workflow is not reused
  - a trusted remote synthesized workflow with the right contract is reusable
- Focused regression suite:
  - `conda run -n graphsmith pytest tests/test_closed_loop.py tests/test_plan_execution.py -q`
  - `89 passed`

## Non-Frontier Check

- `evaluation/holdout_goals` with Groq `llama-3.1-8b-instant` against the hosted
  remote registry: `10/15`

## Why It Matters

This is the first explicit provenance gate for learned coding units. It keeps
Graphsmith from becoming over-eager about reusing arbitrary remote synthesized
programs while still allowing local growth and trusted shared reuse.
