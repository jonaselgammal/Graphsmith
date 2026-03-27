# Coding Frontier Goals

This suite is a separate boundary probe for Graphsmith as a programming-task
substrate rather than only a text/JSON workflow planner.

It focuses on goals that require explicit environment interaction:

- reading and writing files
- running local commands
- running tests
- simple code-oriented edit workflows

These cases are intentionally ahead of current planning capability. The point is
to define a clean, structural frontier for future work after the environment ops
and reusable environment skills exist.

Use:

```bash
graphsmith eval-frontier --goals evaluation/coding_frontier_goals --registry "$REG" \
  --backend ir --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1
```

Most of these should currently fail cleanly. That is acceptable. What matters is
that the tasks are now expressible in terms of graph-native environment skills
instead of being outside the substrate entirely.
