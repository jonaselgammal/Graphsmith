# Sprint 54: Closed-Loop Re-Entry And Single-Skill Fallback

This sprint focused on the specific frontier bottleneck exposed by the new
cross-domain suite: Graphsmith could often detect or generate a missing
single-step capability, but it still failed to turn that into a successful
plan.

## What changed

- broader autogen matching for natural phrasing variants
- per-case registry isolation in `eval-frontier`
- targeted retry when the exact matching generated skill already exists
- deterministic one-skill fallback plan for single-step capabilities

## Key implementation changes

### 1. Autogen matching is less brittle

`extract_spec()` now supports ordered token-subsequence matching instead of
only raw substring matching. This fixes cases like:

- `pretty print this json`
- `count the characters`
- out-of-scope phrasing such as `read a json file from disk`

### 2. Frontier evaluation no longer contaminates itself

`evaluate_frontier_case()` now clones the base registry into a temporary
per-case registry before running closed-loop generation. Generated skills from
one case no longer leak into later cases.

### 3. Existing exact skills can re-enter planning

If the goal maps to a deterministic autogen template and the exact skill
already exists in the registry, Graphsmith now does one targeted retry with
that skill explicitly prepended to the candidate list.

### 4. Single-step capabilities no longer depend entirely on LLM replan

If Graphsmith has already:

- identified the missing capability,
- generated and validated the skill,
- published it,

but the LLM replan still fails, Graphsmith now builds a deterministic
single-node `skill.invoke` plan for true single-step goals.

This is intentionally bounded:

- only for single-step goals
- not for explicit multi-stage goals
- not for loop-shaped requests like `for each`

## Validation

Local:

```bash
conda run -n graphsmith pytest tests/test_autogen.py tests/test_closed_loop.py \
  tests/test_frontier_eval.py tests/test_cli.py -q
```

Observed:
- `126 passed`

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
- `7/12` passed
- `58.3%`

Breakdown:
- all tier-1 single-step cross-domain goals now pass
- tier-3 expected-failure boundary probes behave correctly
- remaining failures are concentrated in tier-2 and mixed multi-stage tasks

## Updated frontier

Graphsmith is now materially better at:
- detecting missing deterministic capabilities outside the example domain
- turning a generated single-step skill into a usable executable plan

Graphsmith is still weak at:
- reinserting a generated skill into a larger multi-stage composition
- mixed-domain plans that require both existing skills and one generated skill

That makes the next architecture step clear: local composition repair around
generated capabilities, not more single-step autogen breadth.
