# Planner Evaluation

## Benchmark v1 (training set)

`evaluation/goals/` — 9 goals used to iteratively develop the planner prompt.
The prompt was refined against these goals. 100% pass rate achieved.

Use for regression testing:
```bash
graphsmith eval-planner --goals evaluation/goals --registry "$REG"
```

## Holdout set (generalisation test)

`evaluation/holdout_goals/` — 15 goals the planner has never been
tuned against. Tests paraphrases, alternate wording, reversed ordering,
implicit multi-step tasks, and unfamiliar phrasing.

Use for generalisation measurement:
```bash
graphsmith eval-planner --goals evaluation/holdout_goals --registry "$REG"
```

## Challenge set (harder tasks with distractors)

`evaluation/challenge_goals/` — 12 goals testing skill selection
under distractor pressure. The registry now contains 15 skills
including 4 distractors (reverse, sort_lines, remove_duplicates,
pretty_print) that the planner must avoid selecting.

Includes: cross-category composition, multi-output with new skills
(word_count, title_case, sentiment), formatting chains with
prefix_lines, and three-skill pipelines with non-obvious ordering.

Use for stress testing:
```bash
graphsmith eval-planner --goals evaluation/challenge_goals --registry "$REG" \
  --backend llm --provider anthropic --model claude-haiku-4-5-20251001
```

## Frontier set (cross-domain generalization probes)

`evaluation/frontier_goals/` is a deliberately broader suite aimed at the
closed-loop path rather than only planner composition inside the example
text-processing domain.

It mixes:
- tier 1: single missing deterministic skills outside the example domain
- tier 2: mixed compositions that require both existing skills and one generated skill
- tier 3: harder boundary probes that are expected to fail cleanly for now

Use it to see where Graphsmith stops generalizing:
```bash
graphsmith eval-frontier --goals evaluation/frontier_goals --registry "$REG" \
  --backend ir --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1
```

## Stress frontier set (progressively harder probes)

`evaluation/stress_frontier_goals/` pushes beyond the regular frontier to map
where Graphsmith starts to break under longer, more heterogeneous tasks.

It mixes:
- moderate cases that should still succeed
- harder cases that should fail cleanly for now
- loop-heavy and branch-heavy workflows
- programming-adjacent, math/statistics, and remote-policy probes

Use it in isolated and cumulative modes:
```bash
graphsmith eval-stress-frontier --goals evaluation/stress_frontier_goals --registry "$REG" \
  --backend ir --mode isolated --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1

graphsmith eval-stress-frontier --goals evaluation/stress_frontier_goals --registry "$REG" \
  --backend ir --mode cumulative --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1
```

## Running evaluations via scripts

The easiest way to run evaluations. Pass provider flags as arguments:

```bash
# All three sets at once
scripts/eval_all.sh --backend llm --provider anthropic --model claude-haiku-4-5-20251001

# Individual sets
scripts/eval_benchmark.sh --backend llm --provider anthropic --model claude-haiku-4-5-20251001
scripts/eval_holdout.sh --backend llm --provider anthropic --model claude-haiku-4-5-20251001
scripts/eval_challenge.sh --backend llm --provider anthropic --model claude-haiku-4-5-20251001

# With mock planner (no API key needed)
scripts/eval_all.sh
```

## Goal format

```json
{
  "goal": "natural language task description",
  "expected_skills": ["skill.id.v1"],
  "expected_output_names": ["output_name"],
  "acceptable_output_names": [["alt1", "alt2"]],
  "min_nodes": 1,
  "required_effects": ["llm_inference"]
}
```

- `expected_output_names`: exact match required for each name
- `acceptable_output_names`: at least one alternative per slot must match
- Both fields are optional; use whichever fits the goal's specificity
