# Sprint 58: Frontier Structural Expectations

This sprint tightened `eval-frontier` so it evaluates structural intent
coverage, not only stop reasons.

## What changed

Frontier goals can now express semantic expectations such as:

- required skill ids
- forbidden skill ids
- required graph inputs
- required output names
- minimum node count
- whether a generated skill must actually appear

For expected-success goals, `eval-frontier` now requires:

- `run_closed_loop()` to succeed
- and the resulting graph to satisfy those structural expectations

For expected-failure goals, the evaluator still checks that the run fails in an
accepted way, but it also records the resulting graph shape when one exists.

## Why this matters

The harder frontier suite exposed that “executable” is not the same as
“semantically faithful.” Structural expectations make the suite much more useful
as a frontier signal because they catch:

- under-specified fallback graphs
- success paths missing required generated skills
- missing grounded inputs such as `prefix`, `substring`, `old`, and `new`

## Validation

```bash
conda run -n graphsmith pytest tests/test_frontier_eval.py tests/test_autogen.py \
  tests/test_closed_loop.py tests/test_cli.py -q
```

Observed:
- `136 passed`

## Current harder-frontier baseline

Groq `llama-3.1-8b-instant`, clean example-only registry:

- `11/12`
- `91.7%`

Interpretation:

- most harder cases now either pass with the expected structure or fail cleanly
- the one remaining genuine expected-success miss is:
  - normalize -> extract keywords -> contains phrase

That makes the next practical target clearer: improve missing-skill detection
and re-entry for mixed existing-skill plus generated-predicate pipelines where
the generated skill is not yet detected/reused reliably.
