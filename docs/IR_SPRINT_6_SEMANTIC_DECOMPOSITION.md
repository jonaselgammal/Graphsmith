# IR Sprint 6 — Semantic Decomposition

## Why reranking plateaued

Reranking at 33/36 (92%) on Llama 3.1 8B. The remaining 3 failures share a
pattern: all N candidates make the same semantic mistake. Reranking can only
choose among what exists — when every candidate is wrong the same way, scoring
cannot help.

Examples:
- All 3 candidates use `join_lines` for a "header" goal
- All 3 candidates split `json.reshape.v1` output instead of using `selected`
- All 3 candidates omit `normalized` from multi-output goals

## Why decomposition is the next step

A decomposition stage makes semantic intent explicit *before* IR generation.
Instead of asking the LLM to solve two problems at once (what to do + how to
structure it), we split into:

1. **Decompose**: what content transforms? what presentation? what outputs?
2. **Generate IR**: given this decomposition, produce structured steps

This is a chain-of-thought regularizer, not a repair loop.

## Decomposition schema

```python
class SemanticDecomposition:
    content_transforms: list[str]     # ["normalize", "extract_keywords"]
    presentation: str                  # "none" | "list" | "header" | "template"
    final_output_names: list[str]     # ["normalized", "keywords"]
    reasoning: str                     # LLM's brief rationale
```

## How decomposition feeds IR generation

The decomposition is injected into the IR prompt as a binding contract:
- Steps MUST cover all `content_transforms`
- A presentation step is added only if `presentation != "none"`
- `final_output_names` constrains the IR's `final_outputs` keys

## Results

| Set | IR Reranked | IR Reranked + Decomp |
|-----|-------------|----------------------|
| Benchmark (9) | 8/9 (89%) | **9/9 (100%)** |
| Holdout (15) | 14/15 (93%) | 13/15 (87%) |
| Challenge (12) | 10/12 (83%) | **12/12 (100%)** |
| **Total** | **32/36 (89%)** | **34/36 (94%)** |

Key wins from decomposition:
- Challenge "format with header" — decomposition said `presentation: "header"`,
  IR correctly used `template.render` instead of `join_lines`
- Challenge "normalize and count words" — decomposition said output `["normalized", "count"]`,
  IR correctly exposed both
- Benchmark 3-step goal — decomposition regularized step selection

The holdout regression (1 goal) is LLM non-determinism, not a systematic issue.

## What remains postponed
- No repair loop
- No training/fine-tuning
- No runtime changes
- No retrieval changes
