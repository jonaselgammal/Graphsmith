#!/usr/bin/env bash
set -euo pipefail

# Run all three evaluation sets with a single registry
REG=$(mktemp -d)
trap "rm -rf $REG" EXIT

echo "Publishing all skills..."
for d in examples/skills/*/; do
  graphsmith publish "$d" --registry "$REG" 2>/dev/null
done
echo ""

echo "=== Benchmark v1 (9 goals) ==="
graphsmith eval-planner --goals evaluation/goals --registry "$REG" "${@}"
echo ""

echo "=== Holdout (15 goals) ==="
graphsmith eval-planner --goals evaluation/holdout_goals --registry "$REG" "${@}"
echo ""

echo "=== Challenge (12 goals) ==="
graphsmith eval-planner --goals evaluation/challenge_goals --registry "$REG" "${@}"
