# Running Evaluations

## Prerequisites

```bash
# Install
pip install -e ".[dev]"

# API keys (choose one method)
# Method 1: environment variable
export GRAPHSMITH_ANTHROPIC_API_KEY=sk-ant-...

# Method 2: .env file (gitignored)
cp .env.example .env
# Edit .env with your keys
```

## 1. Run eval with Claude Haiku (recommended)

```bash
REG=$(mktemp -d)
for d in examples/skills/*/; do graphsmith publish "$d" --registry "$REG" 2>/dev/null; done

# Benchmark (9 goals)
graphsmith eval-planner --goals evaluation/goals --registry "$REG" \
  --backend ir --ir-candidates 3 --decompose \
  --provider anthropic --model claude-haiku-4-5-20251001 --delay 2

# Holdout (15 goals)
graphsmith eval-planner --goals evaluation/holdout_goals --registry "$REG" \
  --backend ir --ir-candidates 3 --decompose \
  --provider anthropic --model claude-haiku-4-5-20251001 --delay 2

# Challenge (12 goals)
graphsmith eval-planner --goals evaluation/challenge_goals --registry "$REG" \
  --backend ir --ir-candidates 3 --decompose \
  --provider anthropic --model claude-haiku-4-5-20251001 --delay 2
```

Expected: 36/36 (100%).

## 2. Run eval with Llama 3.1 8B (Groq)

```bash
export GRAPHSMITH_GROQ_API_KEY=gsk_...

graphsmith eval-planner --goals evaluation/goals --registry "$REG" \
  --backend ir --ir-candidates 3 --decompose \
  --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1 --delay 5
```

Expected: ~86-94% (varies by run).

## 3. Run stability eval (repeated runs)

```bash
GS_EVAL_DELAY=5 scripts/run_stability_eval.sh 3 \
  openai llama-3.1-8b-instant https://api.groq.com/openai/v1

# Analyze results
python scripts/analyze_stability.py /tmp/gs_stability_*/
```

## 4. Collect candidate-level data

```bash
python scripts/collect_candidate_data.py --runs 1 \
  --output-dir /tmp/candidate_dataset \
  --provider anthropic --model claude-haiku-4-5-20251001 --delay 2
```

## 5. Compare planners (direct vs IR)

```bash
GS_EVAL_DELAY=3 scripts/eval_compare_planners.sh \
  --provider anthropic --model claude-haiku-4-5-20251001

python scripts/compare_planners.py \
  /tmp/gs_llm_diag_goals.json /tmp/gs_ir_diag_goals.json
```

## Output locations

| Output | Path |
|--------|------|
| Diagnostics | `--save-diagnostics /tmp/gs_diag_*.json` |
| Failed plans | `--save-failed-plans /tmp/gs_failed_*/` |
| Stability runs | `/tmp/gs_stability_*/` |
| Candidate data | `/tmp/candidate_dataset/` |

## Eval flags reference

| Flag | Default | Description |
|------|---------|-------------|
| `--backend` | `mock` | `mock`, `llm` (direct graph), or `ir` (IR pipeline) |
| `--ir-candidates` | `1` | Number of IR candidates for reranking |
| `--decompose` | off | Enable semantic decomposition stage |
| `--delay` | `0` | Seconds between goals (rate limit protection) |
| `--save-diagnostics` | none | Save per-goal diagnostics JSON |
| `--save-failed-plans` | none | Save failed plan artifacts |
