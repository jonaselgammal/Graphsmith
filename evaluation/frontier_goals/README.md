# Frontier Goals

This suite is meant to probe where Graphsmith currently stops generalizing.

It mixes:
- tier 1: mixed-domain linear compositions that should now be within reach
- tier 2: harder chains with generated predicates/transforms and cross-domain rewiring
- tier 3: current boundary probes around loops, multi-generated plans, and external effects

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
