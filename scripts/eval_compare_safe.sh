#!/usr/bin/env bash
set -euo pipefail

# Rate-limit-safe retrieval mode comparison across all eval sets
# Usage: scripts/eval_compare_safe.sh --backend llm --provider anthropic --model claude-haiku-4-5-20251001

DELAY="${GS_EVAL_DELAY:-2}"  # seconds between goals (configurable via env)

REG=$(mktemp -d)
trap "rm -rf $REG" EXIT

echo "Publishing all skills..."
for d in examples/skills/*/; do
  graphsmith publish "$d" --registry "$REG" 2>/dev/null
done
echo ""

for SET in goals holdout_goals challenge_goals; do
  echo "=== $(echo $SET | tr '_' ' ') ==="
  graphsmith eval-planner --goals "evaluation/$SET" --registry "$REG" \
    --compare-retrieval --delay "$DELAY" \
    --save-results "/tmp/gs_compare_${SET}.json" "${@}"
  echo ""
  echo "  (waiting 10s between sets...)"
  sleep 10
done

echo "Results saved to /tmp/gs_compare_*.json"
