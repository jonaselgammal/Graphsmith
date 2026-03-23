# Sprint 44 — Autogen Smoke Battery

## Scope
- Add a small end-to-end battery for `create-skill-from-goal`
- Add a curated prompt manifest with positive and negative cases
- Actually run the targeted tests and the battery in the project venv

## Why this sprint

After Sprint 43 improved failure reporting, the next step was to
battle-test the bounded autogen path through the user-facing CLI rather
than only through unit-level helpers.

## Changes

### Battery runner
- Added `scripts/run_autogen_battery.py`
- Runs the CLI end-to-end in a temporary output directory

### Curated prompt set
- Added `specs/autogen_prompt_battery.json`
- Includes:
  - known-good generation prompts
  - one out-of-scope prompt
  - one no-match prompt

### User-facing docs
- Added `docs/AUTOGEN_BATTERY.md`
- Linked it from `docs/AUTO_SKILL_CREATION.md`

### Test coverage
- Added `tests/test_autogen_battery.py`
- Extended script tests to include the new battery runner
- Adjusted closed-loop formatting expectation for explicit stop reasons

## What was actually run

Using the project virtualenv created by `./scripts/install.sh`:

- `.venv/bin/pytest tests/test_autogen.py tests/test_closed_loop.py tests/test_autogen_battery.py tests/test_topics_and_diagnostics_v2.py -q`
- `.venv/bin/python scripts/run_autogen_battery.py`

## Results

- Targeted pytest slice: `101 passed`
- Autogen battery: all 5 battery cases passed

## Why this scope is narrow

This sprint does not:
- add new template families
- widen autogen scope
- change planner behavior
- change closed-loop safety boundaries

It only adds a small repeatable regression gate for autogen.
