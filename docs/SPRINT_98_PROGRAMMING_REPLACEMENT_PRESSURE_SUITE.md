# Sprint 98: Programming Replacement Pressure Suite

This sprint adds a dedicated stress suite for the question:

How close is Graphsmith to replacing direct coding on bounded programming
tasks?

## What landed

- New suite: `evaluation/programming_replacement_goals/`
- 13 cases covering:
  - file edit and transform pipelines
  - test execution workflows
  - synthesized coding-workflow reuse
  - loop and branch environment tasks
  - multi-region coding workflows
  - explicit clean-failure probes for iterative/stateful code search
- Updated evaluation docs and running instructions
- Added a regression test that the new suite loads cleanly

## Live results (Groq `llama-3.1-8b-instant`)

Using a fresh local registry populated with all example skills:

- isolated: `7/13`
- cumulative: `8/13`

Key signal:

- cumulative mode does help, but only a little
- registry growth is real (`19 -> 27`, `+8`)
- the main remaining gap is not raw execution, but semantic composition over
  synthesized workflow units and broader multi-region coding tasks
