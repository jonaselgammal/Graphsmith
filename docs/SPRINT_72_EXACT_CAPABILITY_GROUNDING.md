# Sprint 72: Exact Capability Grounding For Near-Miss Plans

## Summary

This sprint tightened the closed-loop acceptance path for a class of
model-sensitive failures where the planner produced an executable graph but
quietly substituted a semantically adjacent capability for the exact one the
goal required.

The motivating cases came from live frontier runs, especially with Claude
Haiku, where goals that needed a generated skill such as `text.contains.v1`
were sometimes "solved" with near-miss plans using `text.equals`,
`text.join_lines.v1`, or other plausible-but-wrong operators.

## What Changed

- Added exact-capability grounding checks in
  `graphsmith/skills/closed_loop.py`.
- If a successful graph is non-empty but omits the exact generated skill
  implied by the goal, Graphsmith no longer accepts it immediately.
- The same check now applies on the replan path after generation/publish, so a
  second near-miss plan does not get accepted as success either.
- Grounding also checks for required public inputs on the exact generated skill
  so cases like `contains` without `substring` are rejected and repaired.
- Added regression coverage for the concrete near-miss pattern:
  `normalize -> summarize -> equals` on a goal that actually requires
  `normalize -> summarize -> contains`.

## Why It Matters

This is an architecture hardening step, not a model-specific tweak.

The goal is to reduce sensitivity to planner style differences across models by
making Graphsmith less willing to accept semantically approximate plans just
because they compile and execute.

## Validation

- `conda run -n graphsmith pytest tests/test_closed_loop.py tests/test_ops.py tests/test_planning_ir.py tests/test_stress_eval.py -q`
- `130 passed`
