# Sprint 52: Closed-Loop And Promotion Upgrade

## Goal

Improve two adjacent capability loops:
- auto skill generation for genuinely missing simple deterministic skills
- auto skill promotion signals from repeated trace evidence

## Closed-loop changes

- Restored a real `graphsmith solve` CLI command in `graphsmith/cli/main.py`.
- `solve` now defaults to the IR backend, so the closed-loop generation path is
  actually exercised by default.
- Missing-skill diagnosis in `graphsmith/skills/closed_loop.py` now checks:
  - whether the autogen-matched skill already exists in the registry/candidate set
  - whether it is already used in compiled candidate plans
- Generated ops are now cleaned up after the bounded loop, avoiding global
  in-process registry pollution across later commands and tests.

## Promotion changes

- `graphsmith/traces/promotion.py` now groups by a richer structural trace
  signature instead of only flat op sequences.
- Promotion candidates now include:
  - `structural_signature`
  - `suggested_skill_id`
  - `suggested_name`
  - `confidence`
- `graphsmith promote-candidates` now prints those richer promotion hints in
  text mode and JSON mode.

## Compatibility

- Added `graphsmith/skills/template.py` with a minimal
  `create_skill_template()` scaffold helper because the autogen regression suite
  still expects that compatibility entrypoint.

## Validation

```bash
conda run -n graphsmith pytest tests/test_closed_loop.py tests/test_traces.py tests/test_cli.py -q
conda run -n graphsmith pytest tests/test_autogen.py tests/test_closed_loop.py tests/test_traces.py tests/test_cli.py tests/test_integration.py tests/test_multi_skill.py -q
```

## Boundaries

These improvements still do not:
- synthesize multi-step or effectful skills
- automatically promote repeated fragments into published skills
- infer a full reusable graph from traces alone

Promotion is still advisory, but the signal is now materially more actionable.
