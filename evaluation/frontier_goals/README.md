# Frontier Goals

This suite is meant to probe where Graphsmith currently stops generalizing.

It mixes:
- tier 1: near-frontier linear chains that still might work
- tier 2: looped or multi-generated chains that should currently fail cleanly
- tier 3: remote/published-only/trust-shaped probes plus external-effect boundaries

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

The current refresh is intentionally harder than the previous suite. It adds:

- tougher success cases with existing-skill plus generated formatting/predicate composition
- more loop-plus-generated boundary cases
- published-only / trust-shaped prompts that the current planner does not yet model explicitly
