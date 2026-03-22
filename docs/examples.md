# Examples

## 1. Normalize and extract keywords

```bash
graphsmith run-interactive --provider anthropic
```

```
  > normalize this text and extract keywords
```

Result:

```
  Plan Summary
  ----------------------------------------
  Steps:
    1. normalize (text.normalize.v1)
    2. extract (text.extract_keywords.v1)
  Outputs:
    - normalized ← normalize.normalized
    - keywords ← extract.keywords
  Effects: llm_inference
```

## 2. Summarize text

```
  > summarize this text
```

Result:

```
  Plan Summary
  ----------------------------------------
  Steps:
    1. summarize (text.summarize.v1)
  Outputs:
    - summary ← summarize.summary
  Effects: llm_inference
```

## 3. Parse JSON and extract field

```
  > parse this JSON and extract the value field
```

Result:

```
  Plan Summary
  ----------------------------------------
  Steps:
    1. extract (json.extract_field.v1)
  Outputs:
    - value ← extract.value
  Effects: pure
```

## 4. Multi-step pipeline with formatting

```
  > clean up the text, extract keywords, and format them as a list
```

Result:

```
  Plan Summary
  ----------------------------------------
  Steps:
    1. normalize (text.normalize.v1)
    2. extract (text.extract_keywords.v1)
    3. format (text.join_lines.v1)
  Outputs:
    - joined ← format.joined
  Effects: llm_inference
```

## 5. Inspect candidates

After any plan, use `:candidates`:

```
  > :candidates

  Candidate 1: ✔ SELECTED
    steps: normalize → extract → format
    outputs: joined
    score: 125

  Candidate 2:
    steps: extract → format
    outputs: joined
    score: 95
    penalties: missing_required_skill: text.normalize.v1

  Candidate 3:
    steps: normalize → extract
    outputs: keywords
    score: 80
    penalties: unnecessary output mismatch
```

## 6. Run a skill directly

```bash
graphsmith run examples/skills/text.normalize.v1 \
  --input '{"text": "  Hello   World  "}'
```

Output:

```json
{"normalized": "hello world"}
```

## 7. Create a custom skill

```bash
graphsmith create-skill text.uppercase.v1
```

Edit `examples/skills/text.uppercase.v1/skill.yaml`, implement the op, then:

```bash
graphsmith validate examples/skills/text.uppercase.v1
```

See [Skills](SKILLS.md) for the full guide.

## 8. Run evaluation

```bash
REG=$(mktemp -d)
for d in examples/skills/*/; do graphsmith publish "$d" --registry "$REG" 2>/dev/null; done

# Benchmark (9 goals)
graphsmith eval-planner --goals evaluation/goals --registry "$REG" \
  --backend ir --ir-candidates 3 --decompose \
  --provider anthropic --model claude-haiku-4-5-20251001 --delay 2

# All sets
for SET in goals holdout_goals challenge_goals; do
  graphsmith eval-planner --goals "evaluation/$SET" --registry "$REG" \
    --backend ir --ir-candidates 3 --decompose \
    --provider anthropic --model claude-haiku-4-5-20251001 --delay 2
done
```
