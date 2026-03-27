# Sprint 86: Nested Region-Aware Evaluation

This sprint does not change planning behavior. It changes how Graphsmith evaluates the structure of lowered control-flow regions, especially loop bodies expressed as `parallel.map` with `inline_graph`.

## What changed

- `graphsmith/evaluation/frontier_eval.py`
  - added recursive graph-node traversal for lowered `parallel.map` inline bodies
  - required skill checks now see nested body skills like `fs.read_text.v1` and `text.contains.v1`
  - structural `node_count` now includes nested region nodes instead of only the outer lowered node

- `tests/test_frontier_eval.py`
  - added a regression proving that a looped file-read plus `contains` workflow passes structural evaluation when the real skills live inside an inline loop body

## Why this matters

Graphsmith already executes nested regions as real subgraphs, but the evaluator was still judging them as opaque single nodes. That created false negatives for coding-style loop workflows and made it harder to tell whether failures were architectural or just measurement artifacts.

This sprint brings evaluation one step closer to the runtime semantics:

- lowered loop regions are still represented compactly
- but structural checks now inspect their real inner skills

## Verification

- `conda run -n graphsmith pytest tests/test_frontier_eval.py tests/test_stress_eval.py -q`
- `11 passed`
- `conda run -n graphsmith python -m compileall graphsmith`

## Evaluation spot check

Local coding frontier with Groq Llama against the fresh local registry:

- before: `5/10`
- after: `7/10`

Main movement:

- `c09` now passes structurally because the evaluator sees:
  - `parallel.map`
  - `fs.read_text.v1`
  - `text.contains.v1`

This is an evaluation correctness sprint, not a new fallback family. The next real roadmap step should be making repair and planning understand nested environment regions as explicitly as evaluation now does.
