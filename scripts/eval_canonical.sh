#!/usr/bin/env bash
set -euo pipefail

# Canonical planner evaluation for release checks and regression tracking.
# Uses the benchmark goal set with the recommended IR configuration.
#
# Usage:
#   scripts/eval_canonical.sh --provider anthropic --model claude-haiku-4-5-20251001

DELAY="${GS_EVAL_DELAY:-2}"
REG=$(mktemp -d)
trap "rm -rf $REG" EXIT

echo "Publishing all skills..."
for d in examples/skills/*/; do
  graphsmith publish "$d" --registry "$REG" 2>/dev/null
done
echo ""

echo "=== Canonical benchmark eval (evaluation/goals) ==="
graphsmith eval-planner \
  --goals evaluation/goals \
  --registry "$REG" \
  --backend ir \
  --ir-candidates 3 \
  --decompose \
  --delay "$DELAY" \
  "${@}"
