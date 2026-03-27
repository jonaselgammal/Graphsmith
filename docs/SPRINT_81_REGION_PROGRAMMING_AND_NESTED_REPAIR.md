## Sprint 81: Region Programming and Nested Repair

This sprint moves Graphsmith one step closer to region-level program repair instead of whole-plan retry.

### What changed

- Added nested runtime repair for invoked local subgraph skills.
- When a `skill.invoke` child trace fails, Graphsmith now:
  - isolates the failing child package,
  - repairs that child graph locally using existing runtime error / trace repair,
  - republishes a repaired local variant,
  - swaps only that callsite in the outer graph,
  - retries execution without regenerating the whole outer plan.

### Why this matters

This is the first execution-path support for treating synthesized subgraphs as real repairable regions. It keeps the outer graph stable while fixing only the broken nested region.

### Scope

The implementation is intentionally narrow:

- targets local repairable subgraph skills (`synth.*` and repaired descendants),
- uses existing deterministic runtime repair and trace-guided region regeneration,
- does not yet do planner-driven arbitrary multi-region replanning.

### Validation

- Focused tests:
  - `tests/test_plan_execution.py`
  - `tests/test_closed_loop.py`
- Added regression for a synthesized loop subgraph that fails at runtime, is repaired as a nested package, and then succeeds on retry.

### Next

The next major step after this remains code/tool environment integration and broader region programming beyond synthesized local subgraphs.
