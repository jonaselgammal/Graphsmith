# Frontier Goals

This suite is meant to probe where Graphsmith currently stops generalizing.

The first three cases are retained as stable near-frontier wins. The remaining
nine are refreshed around the newer architecture:

- tier 1: stable saturated wins
- tier 2: synthesized workflow reuse and mixed composition over coding units
- tier 3: multi-unit coding chains, trust-sensitive reuse, branch/looped coding
  workflows, and broader mixed structured tasks

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

- multi-unit reuse of synthesized coding workflows
- trust-sensitive remote synthesized-skill reuse
- branch/looped environment workflows with follow-up reasoning
- coding-task graphs that mix reusable synth units with generated micro-skills
