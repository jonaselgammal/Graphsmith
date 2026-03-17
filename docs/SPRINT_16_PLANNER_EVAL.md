# Sprint 16 — Planner Evaluation Harness

## Evaluation goals

Measure how reliably the LLM planner produces valid, correct plans
for a set of known goals. Make planning quality visible so prompt
iteration becomes systematic rather than ad hoc.

## Test dataset structure

Each goal is a JSON file in `evaluation/goals/`:

```json
{
  "goal": "normalize text and extract keywords",
  "expected_skills": ["text.normalize.v1", "text.extract_keywords.v1"],
  "expected_output_names": ["normalized", "keywords"],
  "min_nodes": 2,
  "required_effects": ["llm_inference"]
}
```

Fields:
- `goal`: natural language goal string
- `expected_skills`: skill IDs that should appear in skill.invoke nodes
- `expected_output_names`: output names the plan must map
- `min_nodes`: minimum number of graph nodes
- `required_effects`: effects the plan should declare (optional)

## Scoring criteria

Each goal is scored on:

| Check | Pass condition |
|-------|---------------|
| `parsed` | PlanResult status is not "failure" |
| `has_graph` | PlanResult contains a GlueGraph |
| `validates` | GlueGraph passes validate_skill_package |
| `correct_skills` | All expected_skills appear in node configs |
| `correct_outputs` | All expected_output_names are in graph_outputs |
| `min_nodes` | Node count >= min_nodes |
| `no_holes` | No unresolved holes |

Score = count of passed checks / total checks.

## Results format

```json
{
  "provider": "anthropic",
  "model": "claude-haiku-4-5-20251001",
  "timestamp": "...",
  "goals_total": 8,
  "goals_passed": 5,
  "pass_rate": 0.625,
  "results": [
    {
      "goal": "normalize text",
      "status": "pass",
      "checks": {"parsed": true, "has_graph": true, ...},
      "score": 1.0
    }
  ]
}
```

## Limitations

- Evaluation requires a real LLM provider (or mock for structure testing)
- Mock planner always picks the first candidate — evaluation of mock
  is useful for framework testing but not planning quality
- No semantic evaluation of plan logic (only structural checks)
- No execution-time validation (plans are validated, not run)
- Results are not deterministic across LLM runs
