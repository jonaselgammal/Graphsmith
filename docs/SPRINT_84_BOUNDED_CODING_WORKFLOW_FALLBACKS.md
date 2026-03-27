## Sprint 84: Bounded Coding Workflow Fallbacks

This sprint is the first real attempt to use the new environment skills in the
closed-loop path.

### What changed

- Added bounded coding workflow families to `run_closed_loop()`:
  - read file -> normalize
  - read file -> normalize -> write file
  - run pytest
  - run command -> starts_with
  - read file -> replace -> write file
- Reused graph-native subgraph synthesis for side-effect-free structural
  workflows when appropriate, while leaving effectful environment graphs as
  explicit graphs.
- Added focused closed-loop tests for these workflow families.

### Why this matters

This is the first point where Graphsmith starts to use files and commands as
part of the same planning-and-repair substrate instead of keeping them fully
outside the graph world.

### Scope

Still intentionally narrow:

- only a handful of workflow families
- no arbitrary code-edit synthesis
- no planner-specialized coding prompt yet
- no coding-task-specific region repair beyond the general machinery already
  added in earlier sprints

### Intended outcome

The goal is not to make the whole coding frontier pass. The goal is to see
whether the approach composes at all once tasks involve file and command
effects.
