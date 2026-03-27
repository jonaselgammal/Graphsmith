# Sprint 88: Multi-Region Coding Workflows

This sprint extends region programming from single nested regions to a composed
coding workflow with multiple explicit regions.

## What Changed

- Added a bounded multi-region environment fallback in
  `graphsmith/skills/closed_loop.py` for goals of the form:
  - read a file
  - apply one deterministic transform
  - write a new file
  - run `pytest`
- That fallback now synthesizes two separate local subgraph skills:
  - a file-edit region
  - a test region
- The outer plan invokes those synthesized regions as separate `skill.invoke`
  nodes and preserves a dependency edge between them.
- Added focused tests proving:
  - closed-loop planning can build the multi-region workflow
  - runtime repair can patch only the failing nested test region and swap that
    repaired local skill into the outer graph

## Why It Matters

This is the first coding-shaped workflow where Graphsmith preserves a real
program structure across more than one synthesized region. That is closer to the
intended programming-language/compiler direction than a single inline fallback:
the outer program remains stable while one inner region is repaired and
re-published locally.

## Validation

- `conda run -n graphsmith pytest tests/test_closed_loop.py tests/test_plan_execution.py -q`
- `84 passed`
- `conda run -n graphsmith python -m compileall graphsmith`

## Non-Frontier Check

- `evaluation/holdout_goals` with Groq `llama-3.1-8b-instant` against the hosted
  remote registry: `10/15`

## Next

The next useful step is to move beyond bounded workflow families and make the
planner/runtime treat these synthesized coding regions as first-class repair and
reuse units in broader tool-using programs.
