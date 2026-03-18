#!/usr/bin/env bash
set -euo pipefail

# Evaluate planner on challenge set (harder goals with distractors)
REG=$(mktemp -d)
trap "rm -rf $REG" EXIT

for d in examples/skills/*/; do
  graphsmith publish "$d" --registry "$REG" 2>/dev/null
done

echo "=== Challenge (12 goals) ==="
graphsmith eval-planner --goals evaluation/challenge_goals --registry "$REG" \
  "${@}"
