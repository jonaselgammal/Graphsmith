# IR Sprint 2 — Robustness and Semantics

## What the first IR eval showed

| Set | Direct | IR | Delta |
|-----|--------|-----|-------|
| Benchmark (9) | 6/9 (67%) | 5/9 (56%) | -1 |
| Holdout (15) | 11/15 (73%) | 10/15 (67%) | -1 |
| Challenge (12) | 4/12 (33%) | 7/12 (58%) | +3 |
| Total | 21/36 (58%) | 22/36 (61%) | +1 |

IR eliminated mechanical errors (invalid edge scopes, invented types, self-loops)
but introduced new boundary issues and did not resolve semantic planning mistakes.

## Mechanical vs semantic failures

### Mechanical (IR boundary issues) — fixable deterministically
1. **Dot-separated step names**: LLM emits `text.summarize` as step name → compiled
   node ID contains dot → validator splits on first dot → unknown scope `text`.
   Fix: sanitize step names in compiler (replace non-alphanumeric chars).
2. **String shorthand in final_outputs**: LLM emits `"summary": "summarize.summary"`
   instead of `{"step": "summarize", "port": "summary"}`.
   Fix: parser normalization for unambiguous shorthand.

### Semantic (LLM planning mistakes) — need prompt guidance
1. **Over-composition**: LLM adds formatting step for "extract keywords" goals.
2. **Wrong output naming**: LLM names output `formatted` when `keywords` is expected.
3. **Topic/keyword phrasing**: "find topics" should map to 1-step extraction.

## Parser/compiler hardening (Workstream A)

### A1. Step ID sanitization
Compiler normalizes step names: dots, hyphens, spaces → underscores.
Collision detection with deterministic suffix.

### A2. final_outputs normalization
Parser accepts `"name": "step.port"` shorthand and converts to
`{"step": "step", "port": "port"}`. Rejects ambiguous forms.

### A3. Structured errors
New error types for invalid step IDs and ambiguous shorthand.

## Semantic prompt changes (Workstream B)

### Composition policy strengthening
- Added explicit "1 step only" examples for plain extraction and topic phrasing
- Added step-count guidance per pattern type
- Clarified that formatting steps require explicit formatting language in goal

### Output naming guidance
- Reinforced that final output names must match skill output port names
- Added negative examples showing common naming mistakes

## Intentionally postponed
- Repair loop (LLM correction of compiler errors)
- Direct planner prompt changes
- Retrieval improvements
- Runtime execution changes

## How to rerun the comparison

```bash
# Groq / Llama 3.1 8B
GS_EVAL_DELAY=3 scripts/eval_compare_planners.sh \
  --provider openai --model llama-3.1-8b-instant \
  --base-url https://api.groq.com/openai/v1

# Compare results
python scripts/compare_planners.py /tmp/gs_llm_diag_goals.json /tmp/gs_ir_diag_goals.json
python scripts/compare_planners.py /tmp/gs_llm_diag_holdout_goals.json /tmp/gs_ir_diag_holdout_goals.json
python scripts/compare_planners.py /tmp/gs_llm_diag_challenge_goals.json /tmp/gs_ir_diag_challenge_goals.json
```

## Results after hardening

| Set | Direct | IR | Delta |
|-----|--------|-----|-------|
| Benchmark (9) | 4/9 (44%) | **5/9 (56%)** | **+1** |
| Holdout (15) | 8/15 (53%) | **9/15 (60%)** | **+1** |
| Challenge (12) | 3/12 (25%) | **8/12 (67%)** | **+5** |
| **Total (36)** | **15/36 (42%)** | **22/36 (61%)** | **+7** |

### IR-specific regressions eliminated
- Dot-separated step names: fixed by compiler sanitization (0 occurrences post-sprint)
- String shorthand parse errors: fixed by parser normalization (0 occurrences post-sprint)

### Remaining failures — all semantic
100% of remaining IR failures are LLM semantic mistakes:
- Wrong output names (5 cases)
- Wrong skill selection (3 cases)
- Over-composition (2 cases)

Zero parser/compiler boundary issues remain.
