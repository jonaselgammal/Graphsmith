#!/usr/bin/env bash
set -euo pipefail

# Compare retrieval modes on holdout set with diagnostics
REG=$(mktemp -d)
trap "rm -rf $REG" EXIT

for d in examples/skills/*/; do
  graphsmith publish "$d" --registry "$REG" 2>/dev/null
done

for MODE in ranked ranked_recall ranked_broad; do
  echo "=== Holdout ($MODE) ==="
  graphsmith eval-planner --goals evaluation/holdout_goals --registry "$REG" \
    --retrieval-mode "$MODE" \
    --save-diagnostics "/tmp/gs_holdout_${MODE}.json" \
    "${@}"
  echo ""
done

echo "Diagnostics saved to:"
echo "  /tmp/gs_holdout_ranked.json"
echo "  /tmp/gs_holdout_ranked_recall.json"
echo "  /tmp/gs_holdout_ranked_broad.json"
