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

## Running all three

```bash
REG=$(mktemp -d)
for d in examples/skills/*/; do graphsmith publish "$d" --registry "$REG" 2>/dev/null; done

echo "=== Benchmark v1 ==="
graphsmith eval-planner --goals evaluation/goals --registry "$REG" \
  --backend llm --provider anthropic --model claude-haiku-4-5-20251001

echo "=== Holdout ==="
graphsmith eval-planner --goals evaluation/holdout_goals --registry "$REG" \
  --backend llm --provider anthropic --model claude-haiku-4-5-20251001

echo "=== Challenge ==="
graphsmith eval-planner --goals evaluation/challenge_goals --registry "$REG" \
  --backend llm --provider anthropic --model claude-haiku-4-5-20251001

rm -rf "$REG"
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
