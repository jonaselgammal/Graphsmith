#!/usr/bin/env bash
set -euo pipefail

# Safe default-mode evaluation across all three sets with diagnostics
# Usage: scripts/eval_default_safe.sh --backend llm --provider anthropic --model claude-haiku-4-5-20251001

DELAY="${GS_EVAL_DELAY:-2}"

REG=$(mktemp -d)
trap "rm -rf $REG" EXIT

echo "Publishing all skills..."
for d in examples/skills/*/; do
  graphsmith publish "$d" --registry "$REG" 2>/dev/null
done
echo ""

for SET in goals holdout_goals challenge_goals; do
  LABEL=$(echo "$SET" | tr '_' ' ')
  echo "=== $LABEL ==="
  graphsmith eval-planner --goals "evaluation/$SET" --registry "$REG" \
    --delay "$DELAY" \
    --save-diagnostics "/tmp/gs_diag_${SET}.json" \
    --save-failed-plans "/tmp/gs_failed_plans_${SET}" "${@}"
  echo ""
done

echo "Diagnostics saved to:"
echo "  /tmp/gs_diag_goals.json"
echo "  /tmp/gs_diag_holdout_goals.json"
echo "  /tmp/gs_diag_challenge_goals.json"
echo ""
echo "Failed plans saved to /tmp/gs_failed_plans_*/"
echo ""
echo "Inspect diagnostics:"
echo "  python scripts/inspect_diagnostics.py /tmp/gs_diag_*.json"
echo ""
echo "Inspect failed plans:"
echo "  ls /tmp/gs_failed_plans_*/"
echo "  cat /tmp/gs_failed_plans_goals/*.json | python -m json.tool"
