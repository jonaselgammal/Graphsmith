# Stress Frontier Goals

This suite is deliberately beyond the normal frontier set. It is meant to push
Graphsmith on:

- deeper decomposition
- generated-skill reuse across runs
- loop-heavy and branch-heavy workflows
- mixed math / JSON / text / programming-style tasks
- clean refusal on still-out-of-scope tasks

Use it in two modes:

- `isolated`: every case gets a fresh registry clone
- `cumulative`: generated skills accumulate across the suite

Example:

```bash
graphsmith eval-stress-frontier --goals evaluation/stress_frontier_goals \
  --registry "$REG" --backend ir --mode isolated \
  --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1
```

The suite is intentionally mixed:

- some cases should succeed now
- some should fail cleanly now
- some are stretch probes that test whether cumulative registry growth helps

Each goal file supports the same structural checks as the frontier suite, plus:

- `required_ops`: graph ops that must appear in a successful plan

