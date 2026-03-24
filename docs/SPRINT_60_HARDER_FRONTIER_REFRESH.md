# Sprint 60: Harder Frontier Refresh

After the mixed predicate re-entry fix, the previous harder frontier suite was
no longer a useful boundary probe on a fresh registry. This sprint replaces it
with a new set centered on:

- multiple generated skills in one intended success path
- loops plus generated composition
- mixed JSON/text generated chains
- conjunction semantics across multiple generated predicates
- filesystem boundaries

## Current shape of the refreshed frontier

The new suite intentionally contains:

- a small number of near-frontier success cases
- a larger set of tasks that should currently fail cleanly

That makes the suite useful even when the headline pass rate is high, because it
is testing whether Graphsmith succeeds where it should and refuses where it
should.

## Fresh-registry baseline

Provider:
- Groq via OpenAI-compatible API
- model: `llama-3.1-8b-instant`

Observed on a fresh example-only registry:
- `12/12`

Interpretation:
- the refreshed frontier is aligned with current behavior
- Graphsmith still does not solve the harder looped and multi-generated cases
- but it now fails them in the expected bounded ways

## Why this still counts as frontier work

The suite is no longer only about “make the percentage lower.”
It is about maintaining an honest boundary map:

- what should succeed
- what should fail
- how it fails

That is especially important before introducing a shared remote skill
repository, because remote reuse will increase the space of plausible but
incorrect compositions.
