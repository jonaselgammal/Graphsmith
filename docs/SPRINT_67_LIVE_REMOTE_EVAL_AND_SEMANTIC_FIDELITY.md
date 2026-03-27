# Sprint 67: Live Remote Eval And Semantic Fidelity

This sprint was driven by running the planner and frontier suites against the
real hosted Cloudflare registry instead of only local or mock registries.

## What the live runs surfaced

Two code regressions were exposed immediately:

- remote `fetch()` returned a synthetic root path, which broke frontier seeding
- the IR reranking path had two variable-scope bugs in `ir_backend.py`

After those were fixed, the live frontier run exposed the more important issue:

- closed-loop success was being overclaimed for unsupported multi-generated,
  loop-plus-generated, and filesystem-boundary tasks

## What landed

- `graphsmith/registry/client.py`
  - remote fetch now returns a real cached package directory
- `graphsmith/planner/ir_backend.py`
  - fixed `request` / `goal` scope regressions in IR reranking
- `graphsmith/skills/closed_loop.py`
  - added a bounded semantic-fidelity gate that blocks claimed success for
    unsupported frontier shapes
- `evaluation/frontier_goals/*.json`
  - frontier expected-failure cases now explicitly accept
    `semantic_fidelity_blocked`

## Validation

Local regression:

- `conda run -n graphsmith pytest tests/test_registry.py tests/test_planning_ir.py tests/test_cli.py -q`
- `144 passed`
- `conda run -n graphsmith pytest tests/test_closed_loop.py tests/test_frontier_eval.py -q`
- `33 passed`

Live hosted registry runs against:

- `https://graphsmith-remote-registry.graphsmith.workers.dev`

Observed with Groq `llama-3.1-8b-instant`:

- planner goals: `8/9`
- frontier goals: `12/12`

## Why this matters

The remote registry is no longer just reachable. It is now participating in a
meaningful live evaluation loop, and the system behavior over the hosted remote
path is back in line with the intended frontier boundary.
