# Sprint 43 — Auto-Skill Generation Hardening

## Scope
- Improve failure reporting for `create-skill-from-goal`
- Improve stop-reason reporting for closed-loop generation
- Add narrow tests around these bounded failure surfaces

## Why this sprint

The next useful step after traces/promotion was not broader generation
capability, but better battle-testing of the existing bounded autogen
path. This sprint makes failures easier to classify without changing
the safety envelope.

## Changes

### Validation/test result stages
- `validate_and_test()` now reports:
  - `failure_stage`
  - `passed`
- Failure stages are:
  - `registration`
  - `validation`
  - `examples`

### Closed-loop stop reasons
- `ClosedLoopResult` now records `stopped_reason`
- Examples:
  - `initial_plan_succeeded`
  - `missing_skill_not_detected`
  - `generated_skill_validation_failed`
  - `generated_skill_examples_failed`
  - `awaiting_confirmation`
  - `confirmation_declined`
  - `publish_failed`
  - `replan_succeeded`
  - `replan_failed`

### User-facing docs
- `docs/AUTO_SKILL_CREATION.md` now explains autogen failure stages
- `docs/CLOSED_LOOP_SKILL_GENERATION.md` now explains why a loop stops

## Why this scope is narrow

This sprint does not:
- add new template families
- widen generation scope
- relax safety boundaries
- change planning/compiler behavior

It only makes the current bounded system easier to battle-test.

## Validation
- Added tests for:
  - registration / validation / examples failure stages
  - closed-loop stop reasons
  - formatted output including failure stage and stop reason
- Python compile check run locally

## What remains unchanged
- Template matching is still deterministic keyword matching
- Closed-loop generation is still single-skill and bounded
- Generation is still advisory until reviewed/published
