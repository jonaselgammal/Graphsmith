#!/usr/bin/env bash
set -euo pipefail

# Run repeated stability evaluation for IR + decomposition + reranking
# Usage: scripts/run_stability_eval.sh [--runs N] [--provider openai] [--model llama-3.1-8b-instant] [--base-url URL]

RUNS="${1:-3}"
PROVIDER="${2:-openai}"
MODEL="${3:-llama-3.1-8b-instant}"
BASE_URL="${4:-https://api.groq.com/openai/v1}"
DELAY="${GS_EVAL_DELAY:-5}"
OUTDIR="/tmp/gs_stability_$(date +%Y%m%d_%H%M%S)"

mkdir -p "$OUTDIR"

REG=$(mktemp -d)
trap "rm -rf $REG" EXIT

echo "Publishing skills..."
for d in examples/skills/*/; do
  graphsmith publish "$d" --registry "$REG" 2>/dev/null
done

echo ""
echo "Running $RUNS stability eval runs..."
echo "Model: $PROVIDER/$MODEL"
echo "Output: $OUTDIR"
echo ""

for RUN in $(seq 1 "$RUNS"); do
  echo "=== Run $RUN/$RUNS ==="
  for SET in goals holdout_goals challenge_goals; do
    graphsmith eval-planner --goals "evaluation/$SET" --registry "$REG" \
      --backend ir --ir-candidates 3 --decompose \
      --provider "$PROVIDER" --model "$MODEL" --base-url "$BASE_URL" \
      --delay "$DELAY" \
      --save-diagnostics "$OUTDIR/run${RUN}_${SET}.json" \
      2>&1 | grep "^Goals:"
  done
  echo ""
done

echo "All runs complete. Results in: $OUTDIR"
echo ""
echo "Analyze with:"
echo "  python scripts/analyze_stability.py $OUTDIR"
