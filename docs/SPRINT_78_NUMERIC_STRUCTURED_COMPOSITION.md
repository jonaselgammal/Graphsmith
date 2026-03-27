# Sprint 78: Numeric / Structured Composition

This sprint adds a small reusable substrate for composing scalar numeric
subresults into structured outputs instead of adding another goal-specific
fallback.

What changed:

- Added `json.pack`, a pure primitive op that packs arbitrary scalar inputs into
  a JSON object string.
- Added a bounded structured numeric fallback family in
  `graphsmith/skills/closed_loop.py` for:
  - one or two numeric reducers over `values`
  - optional binary divide over a reducer result and a public `divisor`
  - JSON packing + existing `json.pretty_print.v1`
  - optional `text.contains.v1` over the formatted JSON

Why this matters:

- The missing general capability was not “do median+divide” specifically.
- It was “assemble several scalar subresults into a typed structured
  intermediate and keep composing from there.”
- `json.pack` provides that intermediate without pushing more domain-specific
  planner heuristics into the system.

Current scope:

- Pure, bounded, no loops/branches/filesystem.
- Only scalar math reducers/transforms already representable by generated
  single-step skills.
- Intended as a bridge toward richer structured values in the planning/runtime
  substrate, not as the final data model.
