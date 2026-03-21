# Debugging and Traces

## Inspecting evaluation failures

### Save failed plan artifacts

```bash
graphsmith eval-planner --goals evaluation/goals --registry "$REG" \
  --backend ir --ir-candidates 3 --decompose \
  --provider anthropic --model claude-haiku-4-5-20251001 \
  --save-failed-plans /tmp/failed_plans \
  --save-diagnostics /tmp/diag.json
```

### Inspect diagnostics

```bash
python scripts/inspect_diagnostics.py /tmp/diag.json
```

Shows per-goal status with failure classification:
- **PROVIDER**: API errors (rate limits, auth)
- **RETRIEVAL**: needed skills not in shortlist
- **PLANNER**: skills present but plan is wrong

### Inspect failed plan artifacts

```bash
python scripts/inspect_failed_plans.py /tmp/failed_plans/
```

Shows structural issues: self-loops, invalid addresses, multi-source conflicts.

## What a TraceRecord contains

Each trace (from `graphsmith.evaluation.stability.TraceRecord`) captures:

| Field | Description |
|-------|-------------|
| `goal` | The natural language goal |
| `model`, `backend` | Model and backend configuration |
| `decomposition` | Semantic decomposition (content_transforms, presentation, output_names) |
| `candidates` | All N IR candidates with steps, outputs, scores |
| `winning_candidate_index` | Which candidate was selected |
| `graph_nodes`, `graph_outputs` | Compiled graph summary |
| `status`, `failure_type` | Eval outcome |
| `failure_class` | Classified failure (wrong_output_name, wrong_skill_selection, etc.) |

## Debugging specific failure classes

### wrong_output_name

The plan has correct skills but exposes outputs with wrong names.

```bash
# Check what output names the plan used vs what eval expects
python -c "
import json
d = json.loads(open('/tmp/failed_plans/Some_goal.json').read())
print('Plan outputs:', d['plan']['graph']['outputs'])
print('Declared:', [o['name'] for o in d['plan']['outputs']])
"
```

Common cause: LLM names output `cleaned_text` instead of `normalized`,
or `joined` instead of `keywords`.

### wrong_skill_selection

Wrong skill chosen for the goal.

```bash
# Check which skills were used
python -c "
import json
d = json.loads(open('/tmp/failed_plans/Some_goal.json').read())
for n in d['plan']['graph']['nodes']:
    print(n['id'], n.get('config',{}).get('skill_id', n['op']))
"
```

Common cause: `json.reshape.v1` used instead of `json.extract_field.v1`,
or `text.join_lines.v1` used for header goals instead of `template.render`.

### parse_error

LLM returned invalid JSON or the IR couldn't be parsed.

Check the `error` field in diagnostics:
```bash
python -c "
import json
for d in json.loads(open('/tmp/diag.json').read()):
    if d['status'] != 'pass':
        print(d['goal'], ':', d.get('error','')[:100])
"
```

## Comparing planners

```bash
# Run both planners
graphsmith eval-planner --goals evaluation/goals --registry "$REG" \
  --backend llm --provider anthropic --model claude-haiku-4-5-20251001 \
  --save-diagnostics /tmp/direct.json

graphsmith eval-planner --goals evaluation/goals --registry "$REG" \
  --backend ir --ir-candidates 3 --decompose \
  --provider anthropic --model claude-haiku-4-5-20251001 \
  --save-diagnostics /tmp/ir.json

# Compare
python scripts/compare_planners.py /tmp/direct.json /tmp/ir.json
```

## Stability analysis

```bash
# Run 3 repeated evals
scripts/run_stability_eval.sh 3 anthropic claude-haiku-4-5-20251001

# Analyze
python scripts/analyze_stability.py /tmp/gs_stability_*/
```

Shows per-goal stability: always pass, always fail, or intermittent.
