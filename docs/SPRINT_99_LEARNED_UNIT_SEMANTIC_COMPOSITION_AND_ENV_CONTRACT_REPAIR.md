# Sprint 99: Learned-Unit Semantic Composition and Environment Contract Repair

This sprint extends Graphsmith's bounded coding-workflow substrate in a more compositional direction rather than adding another isolated task family.

What changed:

- Added environment workflow matchers and builders for broader programming-shaped compositions:
  - reused file-transform-write-pytest workflow plus generated `contains`
  - the same workflow plus formatting and `contains`
  - `pytest -> summarize -> write report`
  - `read -> replace -> write -> pytest -> summarize`
- Wired those workflows into the shared environment fallback path.
- Tightened environment grounding checks so these workflows require the correct public inputs and outputs.
- Fixed the orchestration order so missing exact generated skills for environment workflows are not preempted by older generic multi-region fallbacks.

Why it matters:

- Graphsmith can now compose learned workflow units with a missing generated micro-skill more reliably.
- Effectful multi-region workflows are less likely to "almost work" with the wrong public contract.
- The system is moving toward semantic composition over learned units rather than only caching solved workflows.

Validation:

- `conda run -n graphsmith pytest tests/test_closed_loop.py -q`
- `conda run -n graphsmith pytest tests/test_plan_execution.py -q`
- `conda run -n graphsmith python -m compileall graphsmith`
- non-frontier live check:
  - `evaluation/holdout_goals` with Groq `llama-3.1-8b-instant`: `12/15`

Current frontier implication:

- The next gap remains broader multi-region semantic orchestration rather than missing basic workflow building blocks.
