# Sprint 45 — Autogen Paraphrase Battery and Closed-Loop Smoke

## Scope
- Broaden the autogen prompt battery with harder paraphrases
- Add one offline smoke check for the bounded closed-loop CLI path
- Actually run the targeted tests, the expanded battery, and the smoke script

## Why this sprint

After Sprint 44 added a basic autogen battery, the next step was to make
that gate slightly less brittle and to cover the user-facing closed-loop
surface without widening capability or depending on a live provider.

## Changes

### Broader prompt battery
- Expanded `specs/autogen_prompt_battery.json`
- Added paraphrases for:
  - `uppercase`
  - `median`
  - `has_key`
- Added one more out-of-scope case and one more no-match case

### Battery harness hardening
- Updated `scripts/run_autogen_battery.py`
- Each case now gets its own temporary output directory
- This avoids false failures when multiple prompts intentionally map to the
  same generated skill ID

### Closed-loop smoke
- Added `scripts/autogen_closed_loop_smoke.sh`
- Runs:
  - `graphsmith solve "compute the median of numbers" --provider echo --auto-approve`
- The expected result is still `replan_failed`, but the script proves that:
  - missing-skill detection ran
  - skill generation ran
  - validation passed
  - stop-reason reporting is visible in the CLI

### User-facing docs
- Updated `docs/AUTOGEN_BATTERY.md`
- Updated `docs/AUTO_SKILL_CREATION.md`
- Updated `docs/CLOSED_LOOP_SKILL_GENERATION.md`

### Test coverage
- Extended `tests/test_autogen_battery.py` for paraphrase coverage
- Added a CLI-level closed-loop assertion in `tests/test_closed_loop.py`
- Extended script checks in `tests/test_topics_and_diagnostics_v2.py`

## What was actually run

Using the project virtualenv:

- `.venv/bin/pytest tests/test_autogen.py tests/test_closed_loop.py tests/test_autogen_battery.py tests/test_topics_and_diagnostics_v2.py -q`
- `.venv/bin/python scripts/run_autogen_battery.py`
- `./scripts/autogen_closed_loop_smoke.sh`

## Results

- Targeted pytest slice: `105 passed`
- Expanded autogen battery: all 10 cases passed
- Closed-loop smoke: detection + generation + validation succeeded and the
  CLI reported `Stopped: replan_failed` as expected for the offline echo path

## Why this scope is narrow

This sprint does not:
- add new autogen template families
- change autogen safety boundaries
- make closed-loop more autonomous
- change planner or registry behavior

It only makes the existing bounded generation workflows easier to
regression-test and easier to trust.
