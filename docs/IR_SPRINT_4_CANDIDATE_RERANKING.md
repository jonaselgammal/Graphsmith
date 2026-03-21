# IR Sprint 4 — Candidate Reranking

## Why prompt-only semantic planning is flattening out

After three sprints of IR prompt refinement, remaining failures are dominated by
semantic LLM mistakes — particularly over-composition — that resist further prompt
engineering. Llama 3.1 8B consistently adds formatting steps to plain extraction
goals even with explicit prohibitions. The prompt is correct; the model doesn't
follow it reliably.

## Why candidate reranking is the next step

Instead of trying harder to prevent the LLM from making mistakes, we generate
multiple candidates and pick the best one deterministically:

1. The LLM generates N independent IR candidates (N=3 default)
2. Each candidate is parsed, normalized, compiled, and validated
3. A deterministic semantic scorer ranks valid candidates
4. The highest-scoring valid candidate wins

This leverages the observation that the LLM often produces the correct plan in
*some* of its attempts — we just need to identify it reliably.

## How candidates are generated

Multiple independent LLM calls with the same prompt. Each call gets a separate
response that may produce a different plan due to LLM sampling. Temperature/
randomness in the provider handles variation naturally.

## How the deterministic semantic scorer works

The scorer analyzes each compiled candidate against the goal text using explicit,
rule-based penalties and rewards:

| Signal | Rule |
|--------|------|
| Over-composition penalty | Formatting steps (join_lines, template.render, prefix_lines) penalized unless goal contains formatting keywords |
| Required step reward | Goal says "clean/tidy" → reward normalize; "capitalize" → reward title_case; etc. |
| Missing required step penalty | Goal says "clean" but no normalize step → penalty |
| Wrong skill family penalty | Text goal using JSON skills (or vice versa) → penalty |
| Output endpoint alignment | Final output name should match the semantic endpoint skill's port name |
| Minimality preference | Fewer steps preferred when semantically equivalent |

The scorer produces a numeric score with a breakdown of each penalty/reward.

## Results

| Set | Direct | IR Single | IR Reranked (3) |
|-----|--------|-----------|-----------------|
| Benchmark (9) | 4/9 (44%) | 6/9 (67%) | **9/9 (100%)** |
| Holdout (15) | 10/15 (67%) | 12/15 (80%) | **14/15 (93%)** |
| Challenge (12) | 2/12 (17%) | 9/12 (75%) | **10/12 (83%)** |
| **Total** | **16/36 (44%)** | **27/36 (75%)** | **33/36 (92%)** |

Over-composition went from 4 cases (IR single) to 0 (IR reranked).
Wrong output names went from 2 to 1.

## What remains intentionally postponed

- No LLM correction/repair loop
- No training or fine-tuning
- No runtime execution changes
- No retrieval changes
- No direct planner modifications
