#!/usr/bin/env bash
set -euo pipefail

# Compare retrieval modes across all three eval sets
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
    --compare-retrieval "${@}"
  echo ""
done
