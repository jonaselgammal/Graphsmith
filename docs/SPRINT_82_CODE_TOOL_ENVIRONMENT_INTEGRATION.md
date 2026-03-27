## Sprint 82: Code / Tool Environment Integration

This sprint adds the first explicit environment-facing execution layer to Graphsmith.

### What changed

- Added first-class primitive ops:
  - `fs.read_text`
  - `fs.write_text`
  - `shell.exec`
- Added deterministic path guards through `allow_roots` so filesystem and process working directories must stay inside declared roots.
- Added validator coverage for op/effect consistency:
  - `fs.read_text` requires `filesystem_read`
  - `fs.write_text` requires `filesystem_write`
  - `shell.exec` requires `shell_exec`

### Why this matters

This moves Graphsmith closer to a real programming substrate. Plans can now explicitly model:

- reading and writing files,
- running local commands,
- declaring those effects in skill contracts,
- validating that effectful behavior is surfaced in the contract instead of hidden in prompts.

### Scope

This is a narrow foundation step, not a full coding-agent runtime:

- no arbitrary code-edit op yet,
- no test-run specialization beyond `shell.exec`,
- no network/API execution layer,
- no planner fallback work aimed at these ops yet.

### Validation

- runtime tests for filesystem roundtrip, bounded subprocess execution, and allowed-root enforcement
- validator tests for missing effect declarations on environment ops

### Next

The next useful step is to lift these environment ops into graph-native reusable skills and then start defining a small coding/task frontier that exercises files, shell commands, and test execution structurally.
