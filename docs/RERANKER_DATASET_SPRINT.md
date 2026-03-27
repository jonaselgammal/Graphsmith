# Reranker Dataset Sprint

## Why winner-only traces are insufficient

The first learned reranker prototype matched the deterministic scorer exactly
(93.2% accuracy, 90.9% ranking accuracy). This is because winner-only data
contains one row per goal/run — the candidate the deterministic scorer already
picked. Without contrast between candidates, the learned model has no new
information to learn from.

## What a proper candidate-level reranker dataset needs

For each (goal, run), we need **all N candidates** with independent labels:

- Candidate A: extract_keywords only → passes eval (label: 1)
- Candidate B: extract_keywords + join_lines → fails eval, wrong output (label: 0)
- Candidate C: parse error → invalid (label: 0)

This gives the reranker contrast: given the same goal, which candidate features
predict passing. The deterministic scorer's pick becomes one of many data points.

## How data is collected

1. Run the IR backend with `candidate_count=3` and `use_decomposition=True`
2. After each goal, access `backend.last_candidates` for all N candidates
3. For each compiled candidate, evaluate it independently against the eval spec
4. Label each candidate with pointwise (pass/fail) and ranking (rank, is_best) labels

## How labels are assigned

### Pointwise
- `candidate_validates`: does the compiled graph pass validation?
- `would_pass_eval`: if this candidate were selected, would it pass all eval checks?
- `failure_class`: if it wouldn't pass, why?

### Ranking
- `rank`: 1-based rank within the goal/run group (1 = best)
- `is_best`: is this the highest-quality candidate in the group?
- `beats_selected`: is this better than what the deterministic scorer picked?

## Results from data collection

### Claude Haiku (1 run, 36 goals, 108 candidates)
| Metric | Value |
|--------|-------|
| Samples | 108 |
| Passing candidates | 67 (62%) |
| Failing candidates | 41 (38%) |
| Mixed groups (have both) | 24/36 (67%) |
| Selected passes | 36/36 (100%) |
| Oracle passes | 36/36 (100%) |
| **Reranking headroom** | **0 goals** |

### Key finding
The deterministic scorer always picks correctly on Claude Haiku. The 41 failing
candidates are all `invalid_candidate` (parse/compile errors), not semantic
errors. There is no semantic contrast for a learned reranker to learn from.

### What the data tells us
1. **Structural contrast exists**: 24/36 groups have both valid and invalid candidates
2. **Semantic contrast is absent on Claude Haiku**: all valid candidates pass eval
3. **Reranking headroom is 0**: no room for a learned reranker to improve
4. **Weaker model data is needed**: Llama 3.1 8B would provide semantic contrast
   (valid candidates with wrong outputs/skills), but Groq was unavailable

### Implication for learned reranking
A learned reranker only has value when the deterministic scorer sometimes picks
the wrong candidate among valid ones. This happens on Llama 3.1 8B (86-94% pass
rate) but not on Claude Haiku (100%). Future work should collect Llama data when
the API is available.

## What remains postponed
- No production learned reranker integration
- No model architecture tuning
- No online scorer replacement
- Llama 3.1 8B data collection (Groq API temporarily unavailable)
