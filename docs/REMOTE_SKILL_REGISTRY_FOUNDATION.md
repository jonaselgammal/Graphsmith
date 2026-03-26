# Remote Skill Registry Foundation

Graphsmith now has a registry abstraction that can support both local and
remote-backed skill discovery without requiring a real network service yet.

## Current building blocks

### Registry backend protocol

`graphsmith/registry/base.py` defines a shared `RegistryBackend` interface for:

- `publish(path)`
- `fetch(skill_id, version)`
- `has(skill_id, version)`
- `search(...)`
- `list_all()`

This keeps planner, CLI, evaluation, and closed-loop codepaths independent from
the concrete registry implementation.

### Local registry

`LocalRegistry` remains the writable source of truth for a developer's local
workspace. Published entries now carry provenance fields so downstream logic can
tell where a skill came from.

### File-backed remote registry

`FileRemoteRegistry` is a mock remote implementation. It is still filesystem
backed, but it models the metadata shape of a shared AI-native skill network:

- remote manifest metadata
- stable registry identity
- publisher metadata
- trust score
- remote reference strings

This is intentionally enough to exercise retrieval, fetch, provenance, and
local-plus-remote aggregation before designing a real service.

### Aggregated registry

`AggregatedRegistry` merges one preferred local registry with zero or more
remote registries.

Current behavior:

- local entries win on duplicate `(id, version)`
- fetch falls back from local to remote
- publish always targets local
- search returns merged provenance-bearing index entries

## Provenance fields

`IndexEntry` now includes:

- `source_kind`
- `registry_id`
- `registry_url`
- `publisher`
- `trust_score`
- `manifest_version`
- `remote_ref`

These fields are the first step toward planner-visible trust and reuse
decisions. Right now they are mainly surfaced through CLI search/show and
available to retrieval/planning code.

## CLI support

Commands that plan, search, inspect, or evaluate can now take
`--remote-registry <path>` and merge that file-backed remote registry with the
local one.

Current supported commands include:

- `graphsmith search`
- `graphsmith show`
- `graphsmith plan`
- `graphsmith plan-and-run`
- `graphsmith run-plan`
- `graphsmith solve`
- `graphsmith eval-planner`
- `graphsmith eval-frontier`

`graphsmith publish` remains local-only by design.

## Current limits

This is not a full remote repository yet.

Missing pieces:

- network transport / service API
- auth and write permissions
- signatures or stronger provenance verification
- remote caching policy
- ranking/trust-aware retrieval
- version resolution beyond exact `(id, version)`
- moderation / abuse controls

For the proposed next-step service and protocol shape, see:

- `docs/REMOTE_SKILL_REGISTRY_V1_DESIGN.md`

## Why this layer matters

The long-term skill network should be optimized for machine reuse rather than
human browsing. That only works if Graphsmith can carry machine-readable skill
contracts and provenance end to end. This foundation puts those concepts in the
core models before a real remote service exists.
