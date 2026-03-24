# Sprint 59: Mixed Predicate Re-Entry

This sprint fixed the remaining genuine expected-success miss in the harder
frontier suite:

- normalize -> extract keywords -> contains phrase

## Root cause

The goal text used `contain` rather than `contains`, and the autogen matcher for
the `contains` template was too narrow. That prevented missing-skill detection
from ever recognizing `text.contains.v1` as the missing capability.

## What changed

- expanded the `contains` template keywords to include `contain`
- added regressions for:
  - autogen matching on `contain a phrase`
  - closed-loop recovery for the keyword-extraction plus `contains` pipeline

## Validation

```bash
conda run -n graphsmith pytest tests/test_autogen.py tests/test_closed_loop.py \
  tests/test_frontier_eval.py tests/test_cli.py -q
```

Observed:
- `138 passed`

## Live result

On a truly fresh example-only registry, the current harder frontier suite now
lands at:

- `12/12`

That means the suite is no longer a real frontier under clean conditions and
needs to be pushed outward again before it remains useful as a boundary probe.
