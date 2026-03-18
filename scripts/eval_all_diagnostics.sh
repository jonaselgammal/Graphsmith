#!/usr/bin/env bash
set -euo pipefail

# Run all eval sets with diagnostics saved to /tmp
REG=$(mktemp -d)
trap "rm -rf $REG" EXIT

echo "Publishing all skills..."
for d in examples/skills/*/; do
  graphsmith publish "$d" --registry "$REG" 2>/dev/null
done
echo ""

echo "=== Benchmark v1 ==="
graphsmith eval-planner --goals evaluation/goals --registry "$REG" \
  --save-diagnostics /tmp/gs_diag_benchmark.json "${@}"
echo ""

echo "=== Holdout ==="
graphsmith eval-planner --goals evaluation/holdout_goals --registry "$REG" \
  --save-diagnostics /tmp/gs_diag_holdout.json "${@}"
echo ""

echo "=== Challenge ==="
graphsmith eval-planner --goals evaluation/challenge_goals --registry "$REG" \
  --save-diagnostics /tmp/gs_diag_challenge.json "${@}"

echo ""
echo "Diagnostics saved to:"
echo "  /tmp/gs_diag_benchmark.json"
echo "  /tmp/gs_diag_holdout.json"
echo "  /tmp/gs_diag_challenge.json"
