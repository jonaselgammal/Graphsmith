# Evaluation

Graphsmith includes a planner evaluation harness with 36 goals across three sets.

## Goal sets

| Set | Goals | Purpose |
|-----|-------|---------|
| Benchmark | 9 | Core single/multi-skill compositions |
| Holdout | 15 | Paraphrased goals, broader coverage |
| Challenge | 12 | Harder goals with distractors, title case, sentiment |

## Running evaluation

### Setup

```bash
REG=$(mktemp -d)
for d in examples/skills/*/; do graphsmith publish "$d" --registry "$REG" 2>/dev/null; done
```

### Recommended command

```bash
graphsmith eval-planner \
  --goals evaluation/goals \
  --registry "$REG" \
  --backend ir \
  --ir-candidates 3 \
  --decompose \
  --provider anthropic \
  --model claude-haiku-4-5-20251001 \
  --delay 2
```

### Run all three sets

```bash
for SET in goals holdout_goals challenge_goals; do
  echo "=== $SET ==="
  graphsmith eval-planner --goals "evaluation/$SET" --registry "$REG" \
    --backend ir --ir-candidates 3 --decompose \
    --provider anthropic --model claude-haiku-4-5-20251001 --delay 2
done
```

### With Llama (Groq)

```bash
graphsmith eval-planner --goals evaluation/goals --registry "$REG" \
  --backend ir --ir-candidates 3 --decompose \
  --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1 --delay 5
```

## Saving diagnostics

```bash
graphsmith eval-planner --goals evaluation/goals --registry "$REG" \
  --backend ir --ir-candidates 3 --decompose \
  --provider anthropic --model claude-haiku-4-5-20251001 \
  --save-diagnostics /tmp/diag.json \
  --save-failed-plans /tmp/failed/
```

### Inspect diagnostics

```bash
python scripts/inspect_diagnostics.py /tmp/diag.json
```

### Inspect failed plans

```bash
python scripts/inspect_failed_plans.py /tmp/failed/
```

## Stability evaluation

Run multiple times to measure variance:

```bash
scripts/run_stability_eval.sh 3 anthropic claude-haiku-4-5-20251001
python scripts/analyze_stability.py /tmp/gs_stability_*/
```

## Expected results

| Model | Total | Notes |
|-------|-------|-------|
| Claude Haiku | 36/36 (100%) | Consistent |
| Llama 3.1 8B | 31-34/36 (86-94%) | Intermittent output naming noise |

## Goal file format

Each goal is a JSON file:

```json
{
  "goal": "Normalize this text and extract keywords",
  "expected_skills": ["text.normalize.v1", "text.extract_keywords.v1"],
  "expected_output_names": ["normalized", "keywords"],
  "min_nodes": 2
}
```
