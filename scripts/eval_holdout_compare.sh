#!/usr/bin/env bash
set -euo pipefail

# Compare retrieval modes on holdout goals
REG=$(mktemp -d)
trap "rm -rf $REG" EXIT

for d in examples/skills/*/; do
  graphsmith publish "$d" --registry "$REG" 2>/dev/null
done

echo "=== Holdout: Retrieval Mode Comparison ==="
graphsmith eval-planner --goals evaluation/holdout_goals --registry "$REG" \
  --compare-retrieval "${@}"
