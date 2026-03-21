# Learned Reranker Prototype

## Why a learned reranker now

The deterministic semantic scorer has taken us to 36/36 on Claude Haiku and
86-94% on Llama 3.1 8B. The remaining failures on weaker models are stochastic
output-naming errors that vary run-to-run. The hand-written scorer has rules for
~15 specific patterns, but can't learn subtle cross-feature interactions.

A learned reranker is a natural next step because:
- It can learn from the trace data we already export
- It sits in the same slot as the deterministic scorer (candidate → score)
- It doesn't change the architecture — just the scoring function
- It's lower risk than a full learned planner

## Why reranking is lower risk than a full learned planner

The IR architecture guarantees structural validity (compiler handles edges, types,
cycles). The learned component only picks among already-valid candidates. Even if
the learned reranker makes a bad pick, the result is still a compilable graph —
just semantically worse. The deterministic scorer provides a fallback.

## Dataset from trace exports

Each training example is a candidate IR from a planning run, labeled by eval outcome:

**Features** (per candidate):
- Step count, skill IDs, output names
- Decomposition alignment (content transforms matched, presentation matched)
- Deterministic score and breakdown components
- Goal text features (word presence for formatting/JSON/etc.)

**Labels**:
- Binary: would this candidate pass eval? (1/0)
- The deterministic score itself (for regression)

## Model approach

Gradient boosted trees (scikit-learn's `GradientBoostingClassifier`) on structured
features. No text embeddings needed — the features are already semantic.

## What is measured

- Accuracy: does the learned reranker pick a passing candidate?
- Ranking quality: for goal groups with mixed pass/fail candidates, does the learned
  reranker rank passing candidates higher?
- Comparison against deterministic scorer

## Offline evaluation results

### Dataset
- 144 rows from 3 stability runs (Llama 3.1 8B) + 1 Claude Haiku run
- 94% pass rate (highly imbalanced — most candidates are winners that passed)
- Train/test split by goal (25 train goals, 11 test goals)

### Results
| Metric | Deterministic | Learned | Notes |
|--------|--------------|---------|-------|
| Test accuracy | 93.2% | 93.2% | Identical on this data |
| Ranking accuracy | 90.9% | 90.9% | Both pick passing candidate 10/11 times |

### Top features learned
1. `goal_mentions_summarize` (0.42) — summarize goals are the most variable
2. `goal_mentions_format` (0.35) — formatting intent is a strong signal
3. `goal_mentions_clean` (0.13) — cleanup goals matter

### Key finding
With **winner-only** diagnostics (1 row per goal per run), the learned reranker
cannot outperform the deterministic scorer. Both have the same information.
The learned reranker's value requires **candidate-level** data (all N candidates
per goal, with labels for each), which the data collection script
(`scripts/collect_reranker_data.py`) is designed to produce.

### Next step
Run `collect_reranker_data.py` with `--runs 5` to get candidate-level data
with ~540 labeled candidates (36 goals × 3 candidates × 5 runs). This should
provide the contrast needed for the learned reranker to potentially outperform
the deterministic scorer on intermittent failures.

## Out of scope

- No end-to-end fine-tuned planner
- No online replacement of deterministic scorer
- No repair loop
- No runtime changes
