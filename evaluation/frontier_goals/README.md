# Frontier Goals

This suite is meant to probe where Graphsmith currently stops generalizing.

The first three cases are carried over from the previous frontier because they
were the last saturated near-frontier wins. The remaining nine are deliberately
harder and broader:

- tier 1: the old saturated near-frontier wins
- tier 2: near-frontier branch and deterministic pipeline cases that should
  still be possible with current bounded repair
- tier 3: much harder loop, math/stats, branch-plus-LLM, multi-generated, and
  programming-adjacent tasks that are expected to expose the real boundary

Use:

```bash
graphsmith eval-frontier --goals evaluation/frontier_goals --registry "$REG" \
  --backend ir --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1
```

Optional semantic expectation fields per goal:

- `required_skill_ids`
- `forbidden_skill_ids`
- `required_graph_inputs`
- `required_output_names`
- `min_node_count`
- `require_generated_skill`

These let the frontier suite check semantic structure, not just whether the
closed-loop path stopped in `success`.

This refresh is intentionally targeted to land around a real boundary for cheap
models. Every case is marked as an intended success, but several require
composition patterns that Graphsmith should not yet solve reliably:

- looped generated-skill composition
- multi-generated chains
- math/stats plus formatting
- branch-plus-LLM subplans
- programming-adjacent and code-ish list pipelines
