#!/usr/bin/env bash
set -euo pipefail

# Evaluate planner on holdout set (generalisation test)
REG=$(mktemp -d)
trap "rm -rf $REG" EXIT

for d in examples/skills/*/; do
  graphsmith publish "$d" --registry "$REG" 2>/dev/null
done

echo "=== Holdout (15 goals) ==="
graphsmith eval-planner --goals evaluation/holdout_goals --registry "$REG" \
  "${@}"
