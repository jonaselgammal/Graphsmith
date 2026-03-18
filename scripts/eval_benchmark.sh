#!/usr/bin/env bash
set -euo pipefail

# Evaluate planner on benchmark v1 (training set)
REG=$(mktemp -d)
trap "rm -rf $REG" EXIT

for d in examples/skills/*/; do
  graphsmith publish "$d" --registry "$REG" 2>/dev/null
done

echo "=== Benchmark v1 (9 goals) ==="
graphsmith eval-planner --goals evaluation/goals --registry "$REG" \
  "${@}"
