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
| `:nodes` | List all nodes in the graph with skills |
| `:graph` | ASCII flow diagram |
| `:graph dot` | Graphviz DOT export |
| `:trace` | Show execution trace with inputs/outputs per step |
| `:inspect <node>` | Show a specific node's inputs and outputs |
| `:rerun` | Rerun same goal (different LLM samples) |
| `:rerun 5` | Rerun with 5 candidates |

### Graph export

Export any plan to DOT or JSON:

```bash
graphsmith export-graph plan.json --format dot -o plan.dot
graphsmith export-graph plan.json --format json
graphsmith export-graph plan.json --format ascii
```

### Debugging workflow

1. `graphsmith run-interactive` — plan a goal
2. `:candidates` — inspect all candidates
3. `:compare` — see why one was chosen
4. `:nodes` — list the graph structure
5. `:graph dot` — export for visualization
6. `:trace` — see execution step by step
7. `:inspect normalize` — check a specific node's I/O

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
