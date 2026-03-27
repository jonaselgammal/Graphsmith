# Sprint 85: Branch And Loop Coding Workflows

This sprint extends the bounded coding-task layer with two new environment-native workflow families:

- branch over `pytest` success/failure and format the output differently per branch
- loop over a list of file paths, read each file, and apply a generated `contains` predicate

## What changed

- `graphsmith/skills/closed_loop.py`
  - added `_goal_matches_pytest_prefix_branch()`
  - added `_goal_matches_loop_read_contains()`
  - tightened `_goal_matches_run_pytest()` so broader multi-stage coding goals do not collapse into the single-step pytest fallback
  - added `_build_run_pytest_prefix_branch_plan()`
  - added `_build_loop_read_contains_plan()`
  - wired both into `_build_environment_fallback_plan()`
  - added grounding checks for both workflow families
  - seeded `text.contains.v1` generation for the looped file-read case
  - allowed this bounded looped filesystem workflow through the semantic-fidelity gate

- `tests/test_closed_loop.py`
  - added regression coverage for the pytest branch formatter path
  - added regression coverage for the looped file-read plus generated `contains` path

## Why this matters

This is the first coding-oriented sprint where the closed-loop path handles non-linear environment workflows:

- a branch based on a real command outcome
- a loop over effectful file operations

That matters more than adding another linear text pipeline because it exercises the same structural properties Graphsmith will need for broader programming tasks:

- observable control flow
- effectful region composition
- generated capability insertion inside larger workflows

## Verification

- `conda run -n graphsmith pytest tests/test_closed_loop.py tests/test_demo_skills.py -q`
- `69 passed`
- `conda run -n graphsmith python -m compileall graphsmith`

## Evaluation spot checks

Old suite sanity check with Groq Llama against the hosted remote registry:

- `evaluation/holdout_goals`: `7/15`

Local coding frontier with Groq Llama against a fresh local registry:

- overall: `5/10`
- moved `c07` to pass
- `c09` now executes via `environment_fallback_succeeded`, but the current evaluator only sees the outer `parallel.map` node, so it still fails structurally

## Main takeaway

Graphsmith can now express bounded branch and loop coding workflows inside the same closed-loop substrate. The next step should not be another linear workflow. It should be making the evaluation and repair stack understand nested environment regions the same way the runtime already does.
