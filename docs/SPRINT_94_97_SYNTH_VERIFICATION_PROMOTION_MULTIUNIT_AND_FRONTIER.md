# Sprints 94–97: Synth Verification, Promotion Weighting, Multi-Unit IR Composition, Frontier Refresh

This batch tightens synthesized-skill reuse, makes quality signals matter in
retrieval, extends the IR planner's bounded synthesized-unit composition, and
refreshes the frontier around the new architecture.

## Sprint 94: Stronger Semantic Verification For Reused Synthesized Units

- Reused synthesized skills are now scored by stronger verification signals:
  - `validated`
  - `smoke_tested`
  - `promoted`
  - trusted remote provenance
- Effectful remote synthesized workflows now require `smoke_tested` before they
  are eligible for reuse.
- Matching synthesized candidates are no longer chosen only by ID/version sort;
  they are ranked by verification and goal/tag alignment.

## Sprint 95: Promotion Signals Affect Retrieval

- Candidate retrieval now gives small deterministic quality bonuses for:
  - `smoke_tested`
  - `promoted`
  - `validated`
  - trusted remote provenance
- This is the first step toward a skill library that compounds in planning
  quality rather than only growing in size.

## Sprint 96: Planner-Native Multi-Unit Composition

- The real IR backend can now deterministically compose:
  - a reused synthesized coding workflow
  - an optional synthesized formatting region
  - a generated or existing follow-up assertion/formatter step
- This extends planner-native synthesized reuse from a 2-step mixed chain to a
  bounded 3-step chain without calling the provider.

## Sprint 97: Frontier Refresh

- Refreshed `evaluation/frontier_goals` to probe the new boundary:
  - synthesized coding workflow reuse
  - mixed multi-unit composition
  - trust-sensitive remote reuse
  - branch/looped coding workflows
  - broader mixed coding + generated micro-skill tasks

## Validation

- Focused tests:
  - `tests/test_closed_loop.py`
  - `tests/test_planner.py`
  - `tests/test_planning_ir.py`
  - `tests/test_frontier_eval.py`
- Live Groq checks:
  - `evaluation/goals`: `9/9`
  - refreshed frontier: `3/12`
