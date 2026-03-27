# Sprint 71: Existing And Mixed Chain Fallbacks

This sprint closes the two most informative stress-frontier success gaps:

- `s01`: mixed existing-skill plus one generated predicate composition
- `s06`: deterministic multi-skill composition using only existing skills

## What changed

- expanded deterministic decomposition in `graphsmith/planner/decomposition.py`
  with additional transform labels:
  - `sort_lines`
  - `remove_duplicates`
  - `join_lines`
  - `pretty_print`
- changed deterministic decomposition ordering to use the position of matched
  phrases/keywords in the goal, instead of heuristic table order
- extended `graphsmith/skills/closed_loop.py`:
  - mixed JSON-plus-generated fallback now allows existing JSON transforms plus
    one generated text capability
  - existing-skill fallback now builds bounded pipelines even when no skill is
    missing, as long as the deterministic chain is already available
- narrowed the multi-generated guard so existing published formatting skills
  like JSON pretty-print do not incorrectly count as a second missing generated
  capability

## Validation

```bash
conda run -n graphsmith pytest tests/test_closed_loop.py tests/test_decomposition_extended.py tests/test_stress_eval.py -q
conda run -n graphsmith python -m compileall graphsmith
```

Result:

- `37 passed`

## Live stress-frontier delta

Against the hosted remote registry and Groq `llama-3.1-8b-instant`:

- isolated mode:
  - before: `9/12`
  - after: `11/12`
- cumulative mode:
  - before: `8/12`
  - after: `10/12`

Key flips:

- `s01` now succeeds via `multi_stage_fallback_succeeded`
- `s06` now succeeds via `existing_pipeline_fallback_succeeded`

## New frontier

The most informative remaining success gap is now:

- `s03`: branch-style sentiment classification plus branch-specific line prefixing

That suggests the next architectural step should be a bounded structural branch
fallback rather than more linear pipeline work.
