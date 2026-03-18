#!/usr/bin/env bash
set -euo pipefail

# Rate-limit-safe holdout evaluation across retrieval modes with diagnostics
# Usage: scripts/eval_holdout_modes_safe.sh --backend llm --provider anthropic --model claude-haiku-4-5-20251001

DELAY="${GS_EVAL_DELAY:-3}"

REG=$(mktemp -d)
trap "rm -rf $REG" EXIT

for d in examples/skills/*/; do
  graphsmith publish "$d" --registry "$REG" 2>/dev/null
done

for MODE in ranked ranked_recall ranked_broad; do
  echo "=== Holdout ($MODE) ==="
  graphsmith eval-planner --goals evaluation/holdout_goals --registry "$REG" \
    --retrieval-mode "$MODE" --delay "$DELAY" \
    --save-diagnostics "/tmp/gs_holdout_${MODE}.json" "${@}"
  echo ""
  echo "  (waiting 15s before next mode...)"
  sleep 15
done

echo ""
echo "Diagnostics saved to:"
echo "  /tmp/gs_holdout_ranked.json"
echo "  /tmp/gs_holdout_ranked_recall.json"
echo "  /tmp/gs_holdout_ranked_broad.json"
echo ""
echo "Inspect with: python scripts/inspect_diagnostics.py /tmp/gs_holdout_*.json"
