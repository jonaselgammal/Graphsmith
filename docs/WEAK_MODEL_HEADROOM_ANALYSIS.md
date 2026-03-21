# Weak-Model Headroom Analysis

## Setup

- **Model**: Llama 3.1 8B Instant (Groq)
- **Configuration**: IR + decomposition + reranking (3 candidates)
- **Runs**: 3
- **Goals**: 36 (9 benchmark + 15 holdout + 12 challenge)
- **Dataset**: 324 candidate samples, 108 goal groups

## Deterministic vs oracle comparison

| Metric | Value |
|--------|-------|
| Deterministic pass rate | 93% (100/108 groups) |
| Oracle pass rate | 93% (100/108 groups) |
| **Reranking headroom** | **0 goals** |
| Better candidate available | 0 groups |

### Per-run breakdown

| Run | Selected passes | Oracle passes | Headroom |
|-----|----------------|---------------|----------|
| 1 | 33/36 | 33/36 | 0 |
| 2 | 33/36 | 33/36 | 0 |
| 3 | 34/36 | 34/36 | 0 |

## Key finding

**The deterministic scorer never picks a failing candidate when a passing one
exists.** In every failing group (8 total), ALL 3 candidates fail the same way.
The scorer is already optimal within the candidate set.

## Candidate statistics

| Metric | Value |
|--------|-------|
| Total candidates | 324 |
| Passing candidates | 261 (81%) |
| Groups with diverse candidates | 43/108 (40%) |
| Groups where all candidates fail | 8/108 (7%) |

## Failure analysis

### Unique failing goals (5 of 36)

| Goal | Fails in | Pattern |
|------|----------|---------|
| Clean text, summarize, list keywords | 3/3 | Missing `summarize` — uses `extract_keywords` + `join_lines` instead |
| Clean, capitalize, extract keywords | 1/3 | Over-composition (5 nodes), wrong output `rendered` |
| Get summary and keywords | 2/3 | Missing `extract_keywords`, parse errors |
| Lowercase and trim | 1/3 | Wrong output `titled` (adds title_case unnecessarily) |
| Normalize, summarize, sentiment | 1/3 | Parse errors (all 3 candidates) |

### Example 1: "Clean the text, write a summary, and list the keywords"

**Expected**: normalize + summarize + extract_keywords, outputs `summary` + `keywords`
**All candidates**: normalize + extract_keywords + join_lines, output `summary` + `joined`

The LLM consistently skips `summarize` and substitutes `join_lines` for it.
This is a semantic planning error shared by all candidates — no amount of
reranking can fix it.

### Example 2: "Just lowercase and trim this text"

**Expected**: normalize, output `normalized`
**All candidates**: normalize + title_case, output `titled`

The LLM adds an unnecessary `title_case` step and exposes `titled` instead
of `normalized`. Again, all candidates make the same mistake.

### Example 3: "Clean this text, then get both a summary and keywords"

**Expected**: normalize + summarize + extract_keywords, outputs `summary` + `keywords`
**Candidates**: 2 parse errors + 1 wrong skill (join_lines instead of extract_keywords)

No valid correct candidate available.

## Conclusion

### Is learned reranking justified?

**No, not at this time.**

The reranking headroom is exactly 0. The deterministic scorer already makes
the optimal selection from available candidates. The remaining failures are
cases where the LLM (Llama 3.1 8B) consistently produces the wrong semantic
plan — all 3 candidates fail the same way.

### Why headroom is 0

The deterministic scorer's rules (penalize unnecessary formatting, reward
required skills, check output names) are well-aligned with the eval spec.
When candidates differ, the scorer reliably picks the better one. The problem
is upstream: the LLM's semantic planning quality, not the scorer's selection.

### What would actually help

1. **Better decomposition** for the 5 failing goals — the decomposition stage
   could constrain the LLM more tightly
2. **Stronger model** — Claude Haiku achieves 36/36 with the same architecture
3. **More candidate diversity** — 3 candidates with N=3 may not be enough;
   N=5 or temperature variation might help
4. **Goal-specific prompt examples** — for the exact failing patterns
