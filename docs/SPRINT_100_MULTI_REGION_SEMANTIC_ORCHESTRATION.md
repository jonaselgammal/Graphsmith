# Sprint 100: Multi-Region Semantic Orchestration

This sprint extends Graphsmith's coding-workflow substrate from "can build regions" to
"can explicitly orchestrate multiple learned regions into a larger effectful workflow."

What changed:

- Refactored `pytest -> summarize -> write report` into:
  - a synthesized test region
  - a synthesized report region
  - an outer orchestrating graph
  - a reusable published workflow wrapper
- Refactored `read -> replace -> write -> pytest -> summarize` into:
  - a synthesized edit region
  - a synthesized test region
  - a synthesized report region
  - an outer orchestrating graph
  - a reusable published workflow wrapper
- Kept first-run plans structurally visible by returning the outer graph while still publishing
  the reusable workflow for later reuse.
- Routed the shared environment fallback path through these orchestrated workflows.

Why it matters:

- Graphsmith can now express larger coding tasks as compositions of smaller learned regions,
  rather than flattening them into one long fallback graph.
- The region boundaries stay inspectable and repairable.
- The generated workflow wrappers become reusable planner-visible units for later tasks.

Validation:

- `conda run -n graphsmith pytest tests/test_closed_loop.py tests/test_plan_execution.py -q`
- `conda run -n graphsmith python -m compileall graphsmith`
- non-frontier live check:
  - `evaluation/goals` with Groq `llama-3.1-8b-instant`: `8/9`

Current implication:

- The next gap is less about building regions and more about letting the normal planner
  compose several learned units with stronger semantic verification.
