#!/usr/bin/env bash
set -euo pipefail

# Compare direct vs IR planner across all three eval sets
# Usage: scripts/eval_compare_planners.sh --provider anthropic --model claude-haiku-4-5-20251001

DELAY="${GS_EVAL_DELAY:-2}"

REG=$(mktemp -d)
trap "rm -rf $REG" EXIT

echo "Publishing all skills..."
for d in examples/skills/*/; do
  graphsmith publish "$d" --registry "$REG" 2>/dev/null
done
echo ""

# Clean output dirs
rm -rf /tmp/gs_direct_* /tmp/gs_ir_*

for BACKEND in llm ir; do
  PREFIX="/tmp/gs_${BACKEND}"
  if [ "$BACKEND" = "llm" ]; then
    LABEL="DIRECT"
    BACKEND_FLAG="llm"
  else
    LABEL="IR"
    BACKEND_FLAG="ir"
  fi

  echo "########################################"
  echo "# ${LABEL} planner"
  echo "########################################"
  echo ""

  for SET in goals holdout_goals challenge_goals; do
    SET_LABEL=$(echo "$SET" | tr '_' ' ')
    echo "=== ${LABEL}: ${SET_LABEL} ==="
    graphsmith eval-planner --goals "evaluation/$SET" --registry "$REG" \
      --backend "$BACKEND_FLAG" \
      --delay "$DELAY" \
      --save-diagnostics "${PREFIX}_diag_${SET}.json" \
      --save-failed-plans "${PREFIX}_failed_${SET}" "${@}"
    echo ""
  done

  echo ""
done

echo "============================================================"
echo "Outputs saved:"
echo ""
echo "DIRECT planner:"
echo "  /tmp/gs_llm_diag_goals.json"
echo "  /tmp/gs_llm_diag_holdout_goals.json"
echo "  /tmp/gs_llm_diag_challenge_goals.json"
echo "  /tmp/gs_llm_failed_*/"
echo ""
echo "IR planner:"
echo "  /tmp/gs_ir_diag_goals.json"
echo "  /tmp/gs_ir_diag_holdout_goals.json"
echo "  /tmp/gs_ir_diag_challenge_goals.json"
echo "  /tmp/gs_ir_failed_*/"
echo ""
echo "Compare:"
echo "  python scripts/compare_planners.py /tmp/gs_llm_diag_goals.json /tmp/gs_ir_diag_goals.json"
echo "  python scripts/compare_planners.py /tmp/gs_llm_diag_holdout_goals.json /tmp/gs_ir_diag_holdout_goals.json"
echo "  python scripts/compare_planners.py /tmp/gs_llm_diag_challenge_goals.json /tmp/gs_ir_diag_challenge_goals.json"
