## Sprint 83: Graph-Native Environment Skills and Coding Frontier

This sprint lifts the new environment ops into reusable published skills and
defines a dedicated coding/task frontier.

### What changed

- Added reusable example skills:
  - `fs.read_text.v1`
  - `fs.write_text.v1`
  - `dev.run_command.v1`
  - `dev.run_pytest.v1`
- Added execution tests proving these can be used as ordinary `skill.invoke`
  nodes in larger graphs.
- Added a composed read-normalize-write workflow test using:
  - `fs.read_text.v1`
  - `text.normalize.v1`
  - `fs.write_text.v1`
- Added `evaluation/coding_frontier_goals/` as a dedicated future-facing probe
  for file, command, and test workflows.

### Why this matters

The environment ops are no longer only primitive runtime capabilities. They now
exist as registry-visible, typed, reusable skills that can be retrieved,
composed, inspected, and eventually promoted like the rest of Graphsmith.

### Scope

This sprint does **not** teach the planner how to solve the coding frontier.
It just makes those tasks part of the same graph-native substrate.

### Validation

- example-skill execution tests
- composed file-processing workflow test
- one non-frontier live planner suite check after the changes
