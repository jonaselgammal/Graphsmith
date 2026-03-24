# Sprint 53: Frontier Suite And Baseline

This sprint adds a dedicated frontier evaluation harness for the closed-loop
solve path, plus the first cross-domain baseline run.

## What was added

- `graphsmith eval-frontier`
- `graphsmith/evaluation/frontier_eval.py`
- `evaluation/frontier_goals/`

The frontier suite is intentionally different from the main planner evals.
It is not primarily about in-domain planner quality. It is about where
Graphsmith currently stops generalizing when it must:

- detect a missing capability
- generate a deterministic skill
- validate and publish it
- replan with that new skill
- combine it with existing graph structure when needed

## Current frontier design

- Tier 1: single missing deterministic skills outside the example text domain
- Tier 2: compositions that mix existing example skills with one missing generated skill
- Tier 3: harder boundary probes, some intentionally expected to fail for now

## First live baseline

Environment:
- provider: Groq via OpenAI-compatible API
- model: `llama-3.1-8b-instant`
- backend: `ir`
- registry: all example skills published

Command:

```bash
conda run -n graphsmith graphsmith eval-frontier --goals evaluation/frontier_goals \
  --registry "$REG" --backend ir \
  --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1 --output-format json
```

Observed result:
- total: 12
- passed: 3
- pass rate: 25%

Breakdown:
- all three expected-failure boundary probes passed as expected
- most expected-success probes failed

Main failure shapes:
- missing skill not detected for some non-text goals
- missing skill detected, skill generated, but replan still failed
- generated capabilities did not re-enter mixed compositions robustly

## Interpretation

This is a useful frontier.

Graphsmith is now reasonably strong at:
- planner composition inside the current example-heavy domain
- guarded branches and bounded loops
- local graph/region repair

Graphsmith is not yet strong at:
- broad missing-capability detection outside the example domain
- reliable closed-loop synthesis for arithmetic / JSON utility skills
- robustly reinserting generated skills into multi-stage mixed-domain plans

That makes the next architecture target clear: strengthen the closed-loop
capability path, especially missing-skill detection and post-generation re-entry
into normal composition.
