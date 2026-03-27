# Sprint 73: Refreshed Live Frontier At 5/12

## Summary

The previous frontier suite had saturated again after the exact-capability
grounding work. This sprint refreshes the frontier set so it is once again a
real boundary probe rather than a regression set.

The new suite keeps the easiest three previous frontier wins and replaces the
remaining nine with broader and harder intended-success tasks across:

- branching
- loops
- math/statistics
- JSON plus formatting
- programming-adjacent text pipelines
- mixed generated and existing skill composition

## Calibration Goal

The target for this refresh was:

- keep the first three easiest cases from the previous suite
- add nine meaningfully harder tasks
- iterate against the live hosted registry with Groq `llama-3.1-8b-instant`
  until at most half of the tasks passed

## Result

The first live calibration run on the hosted remote registry landed at:

- `5/12` passed

That is already below the maximum-half-pass target, so no second redesign pass
was necessary.

## Most Informative Current Failures

The new frontier is now anchored around the following real gaps:

- looped generated-skill composition
- multi-generated text chains after JSON extraction
- math/stats plus formatting composition
- branch-plus-LLM subplans with different branch bodies
- programming-adjacent tasks that should reuse deterministic text pipelines but
  currently get misdiagnosed as missing-skill cases

## Files

- `evaluation/frontier_goals/*.json`
- `evaluation/frontier_goals/README.md`
