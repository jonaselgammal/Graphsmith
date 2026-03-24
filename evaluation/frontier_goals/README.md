# Frontier Goals

This suite is meant to probe where Graphsmith currently stops generalizing.

It mixes:
- tier 1: single missing deterministic skills outside the example text domain
- tier 2: compositions that combine generated deterministic skills with existing example skills
- tier 3: boundary probes that are expected to fail cleanly or remain unstable

Use:

```bash
graphsmith eval-frontier --goals evaluation/frontier_goals --registry "$REG" \
  --backend ir --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1
```
