# Sprint 90: Planner-Visible Synthesized Coding Composition

This sprint extends synthesized coding workflows from simple reuse into mixed
composition.

## What Changed

- Added a bounded mixed environment workflow path in
  `graphsmith/skills/closed_loop.py` for goals shaped like:
  - read file
  - apply one deterministic transform
  - write file
  - run pytest
  - then format the resulting stdout
- That path reuses an existing synthesized
  `workflow:file_transform_write_pytest` skill when present, and composes it
  with a neighboring synthesized formatter region rather than rebuilding the
  whole workflow inline.
- Added planner-visible tags so the reusable synthesized workflow and the
  synthesized formatter region remain discoverable and structurally meaningful.

## Tests

- Added closed-loop tests proving:
  - a mixed goal retrieves and reuses the previously synthesized file workflow
  - the larger plan contains both the reused synthesized workflow and a separate
    synthesized formatter region
- Added execution coverage proving:
  - only the neighboring formatter region gets repaired and swapped when it
    fails
  - the reused workflow region stays untouched

## Why It Matters

This is the first step where Graphsmith composes a learned coding unit inside a
larger program, instead of only reusing one whole synthesized workflow
wholesale. That is the right direction for making synthesized subgraphs behave
like reusable higher-level language constructs.

## Validation

- `conda run -n graphsmith pytest tests/test_closed_loop.py tests/test_plan_execution.py -q`
- `87 passed`
- `conda run -n graphsmith python -m compileall graphsmith`
