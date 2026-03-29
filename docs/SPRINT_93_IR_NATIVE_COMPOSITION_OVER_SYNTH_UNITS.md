# Sprint 93: IR-Native Composition Over Reused Synthesized Units

This sprint moves synthesized coding-unit reuse into the real IR planner path,
not just the mock backend or closed-loop fallback layer.

## What changed

- Added a bounded deterministic pre-LLM composition path in the IR backend for:
  - a reused synthesized coding workflow tagged
    `workflow:file_transform_write_pytest`
  - plus one adjacent follow-up step such as:
    - `text.prefix_lines.v1`
    - `text.contains.v1`
    - `text.starts_with.v1`
- The IR backend now builds and compiles a real `PlanningIR` for that mixed
  composition instead of calling the provider when the structural contract is
  already obvious from the candidate set.
- Added regressions proving:
  - the provider is not called for this bounded structural case
  - the real IR backend composes both:
    - synthesized workflow + existing formatter
    - synthesized workflow + generated assertion

## Why this matters

Graphsmith now treats learned coding workflows more like first-class planner
building blocks in the actual IR pipeline. This is a concrete step away from
one-off fallback orchestration and toward a compounding graph-native skill
library that the normal planner can reuse directly.
