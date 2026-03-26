# Remote Skill Registry V1 Design

This document defines the next concrete design step after the current
file-backed remote registry foundation.

The goal is not to build the full public service immediately. The goal is to
freeze the first real contract so Graphsmith can evolve toward a shared,
AI-native skill network without another large refactor.

## Design goals

The remote registry should optimize for:

- machine reuse, not human browsing
- immutable skill packages
- explicit provenance and trust metadata
- deterministic fetch by exact identity
- simple planner-facing search
- safe local caching
- bounded publish semantics

It should not yet optimize for:

- rich human package discovery UX
- social/community features
- fuzzy dependency resolution
- automatic publishing of every generated skill

## Core object model

The remote system should separate three concepts.

### 1. Skill package blob

Immutable package contents:

- `skill.yaml`
- `graph.yaml`
- `examples.yaml`
- optional future files:
  - `tests.yaml`
  - `trace_summary.json`
  - `README.md`

Blob identity should be content-addressable as well as version-addressable.

Recommended fields:

- `registry_id`
- `skill_id`
- `version`
- `content_hash`
- `size_bytes`
- `created_at`

### 2. Search/index entry

Planner-facing searchable metadata:

- `skill_id`
- `name`
- `description`
- `tags`
- `effects`
- `input_names`
- `output_names`
- `required_input_names`
- `optional_input_names`
- `publisher`
- `source_kind`
- `trust_score`
- `quality_score`
- `validation_status`
- `promotion_origin`
- `content_hash`

This is what retrieval should rank over.

### 3. Provenance record

Separate provenance and trust metadata from the package body.

Recommended provenance fields:

- `publisher_id`
- `publisher_type`
  - `human`
  - `organization`
  - `graphsmith_instance`
- `published_by_graphsmith_version`
- `generated_by_model`
- `promotion_trace_ids`
- `parent_skill_ids`
- `derivation_kind`
  - `human_authored`
  - `llm_generated`
  - `trace_promoted`
  - `human_edited_generated`
- `signature`
- `signature_scheme`
- `attestations`

The planner does not need all of this in its prompt, but the platform should
store it from day one.

## Identity and versioning

The canonical remote identity should be:

- `(registry_id, skill_id, version)`

Versioning rules:

- versions are immutable
- package content cannot change once published
- republishing the same `(skill_id, version)` is rejected
- mutable metadata such as trust or moderation state lives outside the package

Recommended local reference forms:

- exact: `skill_id@version`
- remote exact: `registry_id:skill_id@version`

`latest` resolution should remain a client-side convenience, not the canonical
storage model.

## Publish policy

Shared remote publishing should start strict.

V1 publish eligibility:

- package validates structurally
- package examples pass
- package version is immutable and new
- publisher is authenticated
- provenance metadata is present

Not allowed in V1:

- publishing failed generated skills
- publishing unvalidated drafts
- mutating an existing version

Recommended publish modes:

- `local draft`
- `local promoted`
- `remote publish`

The current local registry remains the place for drafts and experimentation.

## Search API

V1 search should remain simple and structured.

Recommended query surface:

- `q`
- `effect`
- `tag`
- `input_name`
- `output_name`
- `publisher`
- `registry_id`
- `min_trust_score`
- `limit`
- `cursor`

Recommended response shape:

- `results: [IndexEntry]`
- `next_cursor`
- `total_estimate`

Retrieval should stay lexical/structured first. Semantic vector search can be
added later without changing the package contract.

## Fetch API

Fetch should be exact and deterministic.

V1 fetch modes:

- fetch metadata by exact `(registry_id, skill_id, version)`
- fetch package blob by exact `(registry_id, skill_id, version)`

Recommended response fields:

- package manifest
- provenance record
- blob URLs or inlined package data
- integrity hash

Clients should verify integrity before caching.

## Local cache behavior

Graphsmith should treat remote packages as cached immutable artifacts.

Recommended cache rules:

- cache by `(registry_id, skill_id, version, content_hash)`
- never silently rewrite a cached package with different content
- local user-published packages still override remote search duplicates
- remote cache entries are read-only
- cache eviction is size- and age-based, not semantic

Recommended local precedence:

1. local workspace registry
2. local remote-cache
3. live remote registry

## Trust and ranking

Trust should be explicit, not hidden inside retrieval heuristics.

Separate:

- `trust_score`
  - publisher/platform confidence
- `quality_score`
  - empirical signal from validation, examples, traces, reuse, promotion
- `relevance_score`
  - query match

Planner-visible ranking should eventually combine all three, but V1 only needs
to carry them structurally.

Important rule:
- low-trust remote skills may still be retrievable
- but their provenance should be visible and policy should be able to exclude
  them from auto-execution or auto-promotion

## Auth and permissions

V1 should support authenticated publish and public read.

Recommended initial model:

- read:
  - public or token-authenticated
- publish:
  - token-authenticated
- future:
  - organization namespaces
  - approval workflows
  - private registries

Do not bake a single auth provider into the package contract.

## Moderation and abuse controls

The remote registry is not only a storage problem.

V1 needs at least:

- immutable audit log for publish events
- soft-hide / quarantine metadata state
- reportable publisher identity
- package validation gate
- package size limits
- rate limits on publish/search

This matters even before the registry is public, because auto-generated skills
will otherwise make the corpus noisy very quickly.

## Proposed API surface

These can start as internal client/server contracts before becoming public.

### Publish

- `POST /v1/skills`

Request:

- package blob
- package manifest
- provenance metadata

Response:

- canonical identity
- content hash
- publish status

### Search

- `GET /v1/search`

Query parameters:

- `q`
- `effect`
- `tag`
- `input_name`
- `output_name`
- `publisher`
- `registry_id`
- `min_trust_score`
- `limit`
- `cursor`

Response:

- `results`
- `next_cursor`
- `total_estimate`

### Metadata fetch

- `GET /v1/skills/{skill_id}/versions/{version}`

Response:

- index metadata
- provenance
- content hash
- blob reference

### Blob fetch

- `GET /v1/skills/{skill_id}/versions/{version}/blob`

Response:

- package archive or structured package files

## Recommended hosting architecture

Do not start with a complex distributed system.

Recommended first production shape:

- API service
- Postgres for manifests, provenance, and searchable metadata
- object storage for package blobs
- background workers for validation, indexing, and future embeddings

Why this shape:

- simple operational model
- clear separation between metadata and immutable blobs
- easy to add trust/quality pipelines later
- easy to support private or public registries later

I would not start with Git as the primary storage layer. Git is useful for
human workflows, but this registry is fundamentally package-and-index shaped.

## Recommended implementation order

1. finalize manifest and API schemas in-repo
2. add a `RemoteRegistryClient` abstraction
3. add a mock HTTP service for tests
4. add local cache semantics
5. add signed/authenticated publish
6. add trust-aware retrieval and policy gates

## Open design questions

These need explicit decisions before implementation:

- should generated skills require human approval before remote publish?
- should promoted skills carry trace-derived quality metrics in the index?
- should remote registries support namespaces from day one?
- should clients search one registry at a time or fan out across many?
- should the package blob remain file-based YAML or move to an archive format?

My recommendation:

- require approval for remote publish at first
- keep namespaces simple: publisher-scoped or registry-global
- keep package format close to existing local package layout
- keep search fan-out client-side initially
