# Programming Replacement Pressure Goals

This suite is meant to answer a narrower question than the regular frontier:

How close is Graphsmith to acting like a replacement for ordinary direct coding
on small to medium programming tasks?

It is intentionally centered on:

- file reads/writes
- edit + test workflows
- branch and loop control over environment tasks
- reuse of synthesized coding workflows
- multi-region coding plans
- clear clean-failure probes for capabilities that still need richer state or
  iterative program synthesis

Use it with the stress harness in both modes:

```bash
graphsmith eval-stress-frontier --goals evaluation/programming_replacement_goals \
  --registry "$REG" --backend ir --mode isolated \
  --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1 --output-format json

graphsmith eval-stress-frontier --goals evaluation/programming_replacement_goals \
  --registry "$REG" --backend ir --mode cumulative \
  --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1 --output-format json
```

Interpretation:

- `isolated` measures whether each task shape stands on its own
- `cumulative` measures whether synthesized skills and workflow reuse compound
- the final two cases are explicit clean-failure probes rather than current
  expected successes
