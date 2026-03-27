# Sprint 70: Stress Frontier Harness

This sprint adds a separate stress harness for progressively harder
generalization probes.

## What changed

- added `graphsmith/evaluation/stress_eval.py`
- added `graphsmith eval-stress-frontier`
- added `evaluation/stress_frontier_goals/`
- added synthetic trace capture for solved stress cases so the existing
  promotion miner can report repeated workflow fragments

## Why

The regular frontier suite is useful for boundary checks, but it is too small
and too uniform to answer the next set of questions:

- does Graphsmith decompose correctly under much harder goals?
- does cumulative skill generation improve later cases?
- what repeated fragments are emerging that should be promoted?
- where does the system fail cleanly versus overclaiming?

## Modes

- `isolated`
  - each case gets a fresh registry clone
  - measures pure per-case capability
- `cumulative`
  - all cases share one working registry
  - measures generated-skill reuse and registry growth across the run

## Report metrics

The stress report now includes:

- pass rate
- observed successes
- generated case count
- generated skill IDs
- unique generated skill count
- registry size growth
- stop-reason histogram
- promotion candidates mined from synthetic traces

## Validation

```bash
conda run -n graphsmith pytest tests/test_stress_eval.py tests/test_cli.py -q
conda run -n graphsmith python -m compileall graphsmith
```

## Next use

Run the new suite in both `isolated` and `cumulative` mode against:

- the local example registry
- the hosted remote registry
- cheap and stronger models

That should give a much clearer picture of whether Graphsmith is actually
becoming a resilient general programming substrate rather than just passing a
small frontier battery.
