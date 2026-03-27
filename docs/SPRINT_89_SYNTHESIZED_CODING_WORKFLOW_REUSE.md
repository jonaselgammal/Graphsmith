# Sprint 89: Synthesized Coding Workflow Reuse

This sprint makes synthesized coding workflows planner-visible and reusable
instead of recreating them every time the same goal shape appears.

## What Changed

- Added structural metadata and tags to synthesized subgraph skills in
  `graphsmith/skills/closed_loop.py`.
- Multi-region coding synthesis for
  `read file -> transform -> write file -> run pytest`
  now also publishes a synthesized workflow skill tagged as:
  - `workflow:file_transform_write_pytest`
  - `transform:<name>`
  - `coding`, `environment`, `filesystem`, `pytest`
- Added a reuse path that checks the registry for an existing synthesized
  workflow matching the required inputs, outputs, effects, and tags before
  rebuilding the explicit regions.
- Added tests proving:
  - the synthesized workflow becomes retrievable as a planner candidate
  - a second run of the same goal reuses the synthesized workflow directly

## Why It Matters

This is the first step where synthesized coding regions are not only executable
and repairable, but also visible to later planning as reusable higher-level
units. That is a necessary shift away from one-off bounded fallback execution
toward a growing library of graph-native programs.

## Validation

- `conda run -n graphsmith pytest tests/test_closed_loop.py tests/test_plan_execution.py -q`
- `85 passed`
- `conda run -n graphsmith python -m compileall graphsmith`

## Next

The next step is to let broader planning compose these reusable synthesized
coding units inside larger tool-using programs, rather than only reusing one
whole synthesized workflow at a time.
