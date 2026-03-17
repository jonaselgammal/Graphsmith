# Graphsmith Registry Semantics (v1)

## Registry layout

```
<registry_root>/
  index.json                          # flat array of IndexEntry objects
  skills/
    <skill_id>/
      <version>/
        skill.yaml
        graph.yaml
        examples.yaml
```

Default root: `~/.graphsmith/registry/`
Configurable via `LocalRegistry(root=...)` for tests and isolation.

## Skill identity

A skill is uniquely identified by the pair `(id, version)`.
- `id` is a dotted string, e.g. `text.summarize.v1`.
- `version` is a semver-style string, e.g. `1.0.0`.

Publishing the same `(id, version)` pair twice is an error — no
silent overwrite.

## Version resolution

**Exact match only by default.**

`skill.invoke` requires `config.skill_id` and `config.version`.
Both are mandatory. There is no "latest" resolution in v1.

Rationale: ambiguous version resolution is a source of subtle bugs.
Explicit is better than implicit. If "latest" is added later, it
will be behind a documented opt-in flag.

## Index fields

Each entry in `index.json` contains:

| Field | Source |
|-------|--------|
| `id` | `skill.yaml → id` |
| `name` | `skill.yaml → name` |
| `version` | `skill.yaml → version` |
| `description` | `skill.yaml → description` |
| `tags` | `skill.yaml → tags` |
| `effects` | `skill.yaml → effects` |
| `input_names` | names from `skill.yaml → inputs` |
| `output_names` | names from `skill.yaml → outputs` |
| `published_at` | UTC ISO 8601 timestamp at publish time |

The index is regenerated deterministically from disk on startup
if needed; it is an acceleration structure, not the source of truth.

## Search

Text search matches `query` (case-insensitive substring) against:
- `id`
- `name`
- `description`
- `tags` (each tag)

Filter parameters (all optional, AND logic):
- `--effect <e>` — skill must declare this effect
- `--tag <t>` — skill must have this tag
- `--input <name>` — skill must have an input with this name
- `--output <name>` — skill must have an output with this name

Results are sorted by `id` then `version` for determinism.

## Publish

1. Load and validate the skill package.
2. Check that `(id, version)` is not already in the registry.
3. Copy the three YAML files into `skills/<id>/<version>/`.
4. Append an IndexEntry to `index.json`.

## skill.invoke resolution

When the executor encounters a `skill.invoke` node:

1. Read `config.skill_id` and `config.version` (both required).
2. Load the sub-skill from the registry using exact `(id, version)` lookup.
3. Validate the sub-skill.
4. The node's resolved input ports become the sub-skill's graph inputs.
5. Execute the sub-skill recursively through the same runtime.
6. The sub-skill's graph outputs become the node's output ports.

## Recursion depth

- Maximum depth: **10** (configurable).
- The executor tracks a call stack of `(skill_id, version)`.
- If a `(skill_id, version)` pair appears twice on the stack,
  execution fails immediately with a self-recursion error.
- If depth exceeds the limit, execution fails with a depth error.

## Traces for nested execution

`NodeTrace` gains an optional `child_trace: RunTrace | None` field.
When a `skill.invoke` node executes, its `NodeTrace` includes the
full `RunTrace` of the child execution. This makes nested execution
inspectable without a separate persistence system.
