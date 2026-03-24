#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

OUT_FILE="$(mktemp)"
trap 'rm -f "$OUT_FILE"' EXIT

"$PYTHON_BIN" -m graphsmith.cli.main solve \
  "compute the median of numbers" \
  --provider echo \
  --auto-approve >"$OUT_FILE" 2>&1

grep -q "Closed-Loop Result" "$OUT_FILE"
grep -q "Generated: math.median.v1" "$OUT_FILE"
grep -q "Validation: PASS" "$OUT_FILE"
grep -q "Stopped: replan_failed" "$OUT_FILE"

cat "$OUT_FILE"
