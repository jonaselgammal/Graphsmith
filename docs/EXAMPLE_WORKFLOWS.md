# Example Workflows

These workflows use the example skills included in the repository.
All commands use `--mock-llm` for deterministic output without API keys.

## Setup

```bash
pip install -e ".[dev]"

REG=$(mktemp -d)
graphsmith publish examples/skills/text.normalize.v1 --registry "$REG"
graphsmith publish examples/skills/text.extract_keywords.v1 --registry "$REG"
graphsmith publish examples/skills/text.summarize.v1 --registry "$REG"
graphsmith publish examples/skills/json.reshape.v1 --registry "$REG"
graphsmith publish examples/skills/text.join_lines.v1 --registry "$REG"
```

---

## Workflow 1: Normalize text

The most tangible skill — real deterministic transformation.

```bash
graphsmith run examples/skills/text.normalize.v1 \
  --input '{"text":"  AI   agents are transforming SOFTWARE engineering  "}'
```

Output:
```json
{"normalized": "ai agents are transforming software engineering"}
```

Extra whitespace collapsed, mixed case lowered.

---

## Workflow 2: Normalize → Extract keywords

A two-skill chain. Normalize cleans the text, then keyword extraction
sends it to the LLM.

```bash
# Run normalize
graphsmith run examples/skills/text.normalize.v1 \
  --input '{"text":"  AI   agents ARE transforming  SOFTWARE  "}'
# → {"normalized": "ai agents are transforming software"}

# Run extract keywords on the normalized output
graphsmith run examples/skills/text.extract_keywords.v1 \
  --input '{"text":"ai agents are transforming software"}' --mock-llm
# → {"keywords": "Extract the main keywords...ai agents are transforming software"}
```

With a real LLM provider, the keywords output would be:
```json
{"keywords": "AI agents, software, automation"}
```

---

## Workflow 3: Normalize → Summarize

```bash
graphsmith run examples/skills/text.normalize.v1 \
  --input '{"text":"  Cats SLEEP a lot but ARE also agile HUNTERS  "}'
# → {"normalized": "cats sleep a lot but are also agile hunters"}

graphsmith run examples/skills/text.summarize.v1 \
  --input '{"text":"cats sleep a lot but are also agile hunters","max_sentences":1}' \
  --mock-llm
# → {"summary": "Summarize the following text in 1 sentences:\ncats sleep a lot but are also agile hunters"}
```

With a real LLM, the summary would be a concise sentence.

---

## Workflow 4: JSON reshape

Pure deterministic JSON transformation — no LLM needed.

```bash
graphsmith run examples/skills/json.reshape.v1 \
  --input '{"raw_json":"{\"name\":\"Alice\",\"value\":42,\"extra\":\"ignored\"}"}'
```

Output:
```json
{"selected": {"name": "Alice", "value": 42}}
```

Only `name` and `value` fields are kept; `extra` is dropped.

---

## Workflow 5: Full pipeline with traces

Publish → plan → save → execute → trace → promotion.

```bash
TRACES=$(mktemp -d)

# Plan and save
graphsmith plan "normalize text" --registry "$REG" --save /tmp/plan.json

# Execute the plan 3 times with trace persistence
for i in 1 2 3; do
  graphsmith run-plan /tmp/plan.json \
    --input "{\"text\":\"run $i\"}" --mock-llm \
    --registry "$REG" --trace-root "$TRACES"
done

# Inspect traces
graphsmith traces-list --trace-root "$TRACES"
TID=$(graphsmith traces-list --trace-root "$TRACES" | head -1)
graphsmith traces-show "$TID" --trace-root "$TRACES" --summary

# Find promotion candidates
graphsmith promote-candidates --trace-root "$TRACES"
```

---

## Workflow 6: Real LLM planning

Requires an API key. See [provider architecture](SPRINT_08A_PROVIDER_ARCHITECTURE.md).

```bash
export GRAPHSMITH_ANTHROPIC_API_KEY=sk-ant-...

graphsmith list-models --provider anthropic

graphsmith plan "normalize text and extract keywords" \
  --backend llm --provider anthropic \
  --model claude-haiku-4-5-20251001 --registry "$REG" \
  --save /tmp/real_plan.json --save-on-failure /tmp/debug.json

# If plan succeeds, execute it
graphsmith run-plan /tmp/real_plan.json \
  --input '{"text":"AI agents are transforming software engineering"}' \
  --mock-llm --registry "$REG"
```

---

## Cleanup

```bash
rm -rf "$REG" "$TRACES"
```
