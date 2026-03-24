# Sprint 55: Multi-Stage Generated Skill Composition

This sprint tackled the next frontier bottleneck after single-step autogen
re-entry: goals where Graphsmith needs to insert a generated skill into a
larger, otherwise ordinary pipeline.

## What changed

- deterministic multi-stage fallback composition in `closed_loop.py`
- focused only on simple linear text pipelines
- test helper fix so temp registries used in closed-loop tests actually contain
  the example skills they claim to contain

## New fallback behavior

When all of the following are true:

- the goal is multi-stage,
- a generated skill has already been validated and published,
- full LLM replan still fails,
- the surrounding plan can be resolved as a simple linear text pipeline,

Graphsmith now builds the fallback graph directly from deterministic
decomposition plus exact registry skill ids.

This currently covers cases like:

- `normalize -> uppercase`
- `summarize -> uppercase`
- `normalize -> char_count`
- `extract_keywords -> uppercase`

## Safety bounds

The new fallback is intentionally limited:

- text pipelines only
- linear chains only
- no loops
- no branch semantics
- no config-bearing generated transforms
- no mixed math/JSON chains

Those limits are deliberate. They keep the system from over-claiming success on
goals where composition order or configuration still requires stronger
reasoning.

## Validation

```bash
conda run -n graphsmith pytest tests/test_closed_loop.py tests/test_autogen.py \
  tests/test_frontier_eval.py tests/test_cli.py -q
```

Observed:
- `128 passed`

## Live frontier result

Provider:
- Groq via OpenAI-compatible API
- model: `llama-3.1-8b-instant`

Command:

```bash
conda run -n graphsmith graphsmith eval-frontier \
  --goals evaluation/frontier_goals \
  --registry "$REG" \
  --backend ir \
  --provider openai \
  --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1
```

Observed on a clean example-only registry:
- `11/12` passed
- `91.7%`

Passing newly because of multi-stage fallback:
- `f05` normalize then uppercase
- `f06` summarize then uppercase
- `f07` normalize then char_count
- `f08` extract keywords then uppercase

Boundary probes still fail cleanly:
- `f09` median then pretty-print json
- `f10` read file and pretty print
- `f11` loop median lists

## Remaining frontier

The one remaining failure is:
- `f12` normalize, summarize, and check whether the summary contains a phrase

That is a useful remaining boundary because it needs more than just graph
rewiring:

- the generated `contains` skill is config-bearing
- the goal leaves the phrase underspecified
- a valid composition needs both structural planning and argument grounding

So the next architecture step is not broader fallback chaining. It is better
handling for generated skills that require grounded configuration or constants.
