#!/usr/bin/env bash
set -euo pipefail

# Small offline smoke test for the main user-facing commands.
# This intentionally avoids network calls and does not launch the UI server.

REG=$(mktemp -d)
trap "rm -rf $REG" EXIT

for d in examples/skills/*/; do
  graphsmith publish "$d" --registry "$REG" 2>/dev/null
done

echo "Smoke: plan"
graphsmith plan "summarize text" \
  --registry "$REG" \
  --output-format json >/dev/null

echo "Smoke: plan --show-retrieval"
graphsmith plan "summarize text" \
  --registry "$REG" \
  --show-retrieval >/dev/null

echo "Smoke: plan-and-run"
graphsmith plan-and-run "normalize text" \
  --registry "$REG" \
  --input '{"text":"  Hello   World  "}' \
  --output-format json >/dev/null

echo "Smoke: ui command surface"
graphsmith ui --help >/dev/null

echo "Smoke checks passed."
