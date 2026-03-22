# Debugging

## graphsmith doctor

Check system readiness before debugging:

```bash
graphsmith doctor
```

Verifies: Python version, dependencies, API keys, skill count.

## Inspecting failures

### Save artifacts

```bash
graphsmith eval-planner --goals evaluation/goals --registry "$REG" \
  --backend ir --ir-candidates 3 --decompose \
  --provider anthropic --model claude-haiku-4-5-20251001 \
  --save-diagnostics /tmp/diag.json \
  --save-failed-plans /tmp/failed/
```

### Diagnostics summary

```bash
python scripts/inspect_diagnostics.py /tmp/diag.json
```

Classifies failures as:
- **PROVIDER** — API errors (rate limits, auth)
- **RETRIEVAL** — needed skills not in shortlist
- **PLANNER** — skills present but plan is wrong

### Failed plan inspection

```bash
python scripts/inspect_failed_plans.py /tmp/failed/
```

Checks for: self-loops, invalid addresses, multi-source conflicts, wrong outputs.

## Interactive debugging

In `graphsmith run-interactive`, after a plan:

| Command | What it shows |
|---------|---------------|
| `:candidates` | All N candidates with steps, scores, penalties |
| `:compare` | Selected vs best alternative with skill differences |
| `:decomposition` | Semantic decomposition (content transforms, presentation) |
| `:rerun` | Rerun same goal (different LLM samples) |
| `:rerun 5` | Rerun with 5 candidates |

## Common failure classes

### wrong_output_name

The plan has correct skills but uses wrong output port names.

```bash
python -c "
import json
d = json.loads(open('/tmp/failed/Some_goal.json').read())
print('Plan outputs:', d['plan']['graph']['outputs'])
"
```

**Cause**: LLM names output `cleaned_text` instead of `normalized`.

### wrong_skill_selection

Wrong skill chosen for the goal.

**Cause**: LLM picks `json.reshape.v1` instead of `json.extract_field.v1`,
or `text.join_lines.v1` for a header task instead of `template.render`.

### parse_error

LLM returned invalid JSON.

```bash
python -c "
import json
for d in json.loads(open('/tmp/diag.json').read()):
    if d['status'] != 'pass':
        print(d['goal'], ':', d.get('error','')[:80])
"
```

## Comparing planners

```bash
# Direct planner
graphsmith eval-planner --backend llm --provider anthropic \
  --model claude-haiku-4-5-20251001 --registry "$REG" \
  --save-diagnostics /tmp/direct.json

# IR planner
graphsmith eval-planner --backend ir --ir-candidates 3 --decompose \
  --provider anthropic --model claude-haiku-4-5-20251001 --registry "$REG" \
  --save-diagnostics /tmp/ir.json

# Compare
python scripts/compare_planners.py /tmp/direct.json /tmp/ir.json
```
