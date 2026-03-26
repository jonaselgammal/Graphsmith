# Sprint 62: Remote Registry V1 Design

This sprint does not add a new runtime feature. It defines the next concrete
architecture step after the file-backed remote registry foundation.

## Deliverable

A v1 design for the future shared Graphsmith skill network in:

- `docs/REMOTE_SKILL_REGISTRY_V1_DESIGN.md`

## Main decisions

- treat the remote registry as metadata + immutable package blobs
- keep canonical identity exact: `(registry_id, skill_id, version)`
- separate package contents from provenance/trust records
- start with authenticated publish and simple structured search
- keep local drafts local; only validated immutable packages are eligible for
  shared remote publish
- favor API service + Postgres + object storage over a Git-first design

## Why this order

The current codebase now has enough registry abstraction to support local and
remote backends. The next risk is not implementation effort, but designing the
wrong contract and then baking it into planner, cache, and publish flows.

This sprint fixes that by making the service boundary explicit before the real
remote service is built.

## Expected next implementation step

The next concrete build step should be:

- schema models for remote manifests and API payloads
- a `RemoteRegistryClient`
- a mock HTTP service used in tests
- local remote-cache semantics
