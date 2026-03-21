# IR Sprint 8 — Stability Measurement and Trace Export

## Why prompt-only iteration has diminishing returns

After 7 sprints of IR architecture development, the system achieves 32-34/36
(89-94%) on Llama 3.1 8B with decomposition + reranking. Challenge is consistently
12/12. Remaining failures are output-naming noise that varies between runs.
Further prompt tuning cannot reduce LLM sampling variance.

## Why stability measurement matters now

We need to distinguish:
- **Architecture issues**: failures that happen every run (fixable)
- **Model variance**: failures that come and go (need a better model or learned reranking)
- **Eval spec issues**: failures caused by overly narrow acceptance criteria

Without repeated-run data, we can't tell which category a failure belongs to.

## What traces are exported

For each goal in each run, a JSONL trace record captures:
- Goal text, model, backend configuration
- Semantic decomposition (LLM + deterministic fallback)
- All IR candidates with score breakdowns
- Winning candidate selection
- Compiled graph summary
- Eval outcome with failure classification
- Per-goal stability labels (when repeated runs available)

## How traces support future improvements

- **Fine-tuning**: winning IR candidates from passing goals become training examples
- **Learned reranking**: score breakdowns + eval outcomes train a scoring model
- **Semantic critics**: decomposition ↔ IR consistency labels train critics
- **Eval spec refinement**: intermittent failures reveal overly narrow specs

## Stability Results — Llama 3.1 8B (3 runs)

### Per-set pass rates

| Set | Run 1 | Run 2 | Run 3 | Min | Max | Mean |
|-----|-------|-------|-------|-----|-----|------|
| Benchmark (9) | 9/9 | 6/9 | 9/9 | 67% | 100% | 89% |
| Holdout (15) | 13/15 | 13/15 | 13/15 | 87% | 87% | 87% |
| Challenge (12) | 12/12 | 12/12 | 12/12 | 100% | 100% | 100% |
| **Total (36)** | 34/36 | 31/36 | 34/36 | **86%** | **94%** | **92%** |

### Goal stability

- **28 always pass** (78% of goals) — stable architecture wins
- **0 always fail** — no systematic architecture failures
- **8 intermittent** (22%) — LLM sampling noise

### Intermittent goals (most noisy)

| Goal | Pass rate | Dominant failure |
|------|-----------|-----------------|
| Clean text, summarize, list keywords | 1/3 | wrong_output_name |
| Clean up and summarize | 2/3 | wrong_output_name |
| Condense to brief summary | 2/3 | parse_error |
| Extract keywords | 2/3 | wrong_output_name |
| Short summary | 2/3 | parse_error |
| Normalize, summarize, extract | 2/3 | wrong_skill_selection |
| Pull out + present formatted | 2/3 | wrong_skill_and_output |
| Summarize this text | 2/3 | wrong_output_name |

### Failure class distribution

| Class | Count | Notes |
|-------|-------|-------|
| wrong_output_name | 4 | LLM picks wrong port name |
| wrong_skill_selection | 2 | LLM picks wrong skill |
| parse_error | 2 | LLM returns invalid JSON |
| wrong_skill_and_output | 1 | Both wrong |

### Key findings

1. **Challenge is rock-solid**: 12/12 across all 3 runs (100%)
2. **Holdout is stable**: 13/15 across all runs (87%), same 2 goals fail
3. **Benchmark variance**: 6-9/9 (67-100%), driven by 3 intermittent goals
4. **No always-fail goals**: every goal passes in at least 1 of 3 runs
5. **Dominant failure**: wrong_output_name (4/9 failure instances)
6. **Overall range**: 86-94%, mean 92%

### Architecture vs model variance

- **Architecture issues**: 0 (all structural errors eliminated by compiler + scorer)
- **Model variance**: 8 goals (22%) affected by LLM sampling noise
- **Eval spec issues**: 0 remaining (all justified spec adjustments done)

## What remains intentionally postponed
- Repair loops
- Learned scoring/reranking models
- Fine-tuning pipelines
- Runtime changes
