# IR Planner Evaluation Comparison

**Model**: Llama 3.1 8B Instant (Groq)
**Last updated**: 2026-03-20

## Sprint 6 Results — Semantic Decomposition (latest)

| Set | Direct | IR Reranked | IR Decomp+Reranked |
|-----|--------|-------------|---------------------|
| Benchmark (9) | ~4-8 | 8/9 (89%) | **9/9 (100%)** |
| Holdout (15) | ~9-10 | 14/15 (93%) | 13/15 (87%) |
| Challenge (12) | ~2-8 | 10/12 (83%) | **12/12 (100%)** |
| **Total (36)** | **~16-25** | **32/36 (89%)** | **34/36 (94%)** |

## Historical progression

| Sprint | Method | Total | Key change |
|--------|--------|-------|------------|
| 1 | IR single | 22/36 (61%) | Initial IR architecture |
| 2 | IR single | 22/36 (61%) | Parser/compiler hardening |
| 3 | IR single | 24/36 (67%) | Semantic prompt v3 |
| 4 | IR reranked (3) | 33/36 (92%) | Candidate reranking + scorer |
| 5 | IR reranked (3) | 33/36 (92%) | Eval spec fixes + type normalization |
| 6 | IR decomp+reranked | 34/36 (94%) | Semantic decomposition stage |
| 7 | IR decomp+reranked | 32-34/36 (89-94%) | Decomp parse hardening + eval fixes |
| 8 | IR decomp+reranked (3 runs) | 31-34/36 (86-94%, mean 92%) | Stability measurement |
| 9 | IR decomp+reranked (Claude) | **36/36 (100%)** | extract_field decomp fix |

## Pipeline

```
goal → retrieve skills → decompose (LLM) → condition IR prompt
     → generate 3 IR candidates (LLM) → compile each → score each
     → select best → validate → return
```

Total LLM calls per goal: 4 (1 decomposition + 3 IR candidates)

## Remaining 2 failures

Both are LLM non-determinism on holdout goals — vary between runs.
Challenge set is now 100%.

## What each stage eliminates

| Stage | Eliminates |
|-------|-----------|
| IR compiler | Invalid edges, types, self-loops, cycles |
| Scorer | Over-composition, wrong output names |
| Reranking | Single-candidate variance |
| Decomposition | Consistent wrong-candidate families (header=join_lines) |
