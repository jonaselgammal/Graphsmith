# Sprint 101: Planner-Native Composition Over Learned Workflows

This sprint extends the real IR planner path so it can treat more than one
synthesized coding workflow as a reusable subproblem solver, instead of relying
only on one hardcoded workflow shape.

What changed:

- Generalized structural synthesized-workflow selection in the IR backend:
  - supports multiple workflow tags instead of only `workflow:file_transform_write_pytest`
  - scores workflow candidates against goal shape and contract
- Strengthened planner-side semantic verification for structural follow-ups:
  - follow-up selection now prefers goal-aligned formatting/assertion steps
  - output-port selection is aligned to goal intent instead of just taking the
    first sorted port
- Made structural IR synthesis workflow-input driven:
  - uses the workflow's declared required inputs instead of a hardcoded
    `input_path/output_path/cwd` contract

Why it matters:

- Learned workflow units are becoming planner-native building blocks rather than
  only closed-loop fallback artifacts.
- The planner can now pick the right synthesized workflow when several learned
  workflows are available.
- Composition quality is less sensitive to arbitrary candidate ordering.

Validation:

- `conda run -n graphsmith pytest tests/test_planning_ir.py tests/test_closed_loop.py tests/test_plan_execution.py -q`
- `conda run -n graphsmith python -m compileall graphsmith`

Live note:

- A non-frontier holdout eval on Groq returned all-parse-failures across the
  board during this sprint. Local planner/backend tests pass, so that live run
  currently looks more like provider instability than a deterministic regression.
