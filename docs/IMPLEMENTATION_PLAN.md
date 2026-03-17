# Graphsmith Implementation Plan

## Goal

Create a minimal open-source reference implementation of:
- a portable Graphsmith spec
- a deterministic runtime
- a local searchable skill registry
- an LLM planner that composes skills into glue graphs
- trace recording for later procedural-memory work

## Phases

### Phase 0 — repo scaffold
Create monorepo structure:
- `graphsmith/` Python package
- `tests/`
- `examples/`
- `schemas/`
- `docs/`
- `tasks/`

### Phase 1 — spec and schema
Implement:
- Pydantic models for skill contracts and graph bodies
- JSON Schema export
- YAML parser
- validation CLI

Success criteria:
- `graphsmith validate examples/skills/text.summarize.v1` passes
- invalid files fail with actionable errors

### Phase 2 — runtime core
Implement:
- internal graph IR
- topological sort
- primitive op executor
- nested `skill.invoke`
- deterministic context passing
- trace capture

Success criteria:
- example skills run locally
- repeated runs with same deterministic inputs produce same graph behavior except LLM outputs

### Phase 3 — local registry
Implement:
- registry directory layout
- publish and fetch commands
- metadata index
- search API or CLI
- keyword and filter search

Success criteria:
- skills can be published locally
- search by tag, effect, and input type works

### Phase 4 — planner/composer
Implement:
- planner interface
- prompt builder
- candidate skill retrieval
- glue graph generation
- glue graph validation
- failure reporting with unresolved holes

Success criteria:
- given a task prompt and registry, planner returns a valid glue graph for simple tasks

### Phase 5 — traces and promotion prototype
Implement:
- trace store
- recurring fragment detector stub
- candidate promotion output format

Success criteria:
- runtime stores traces
- recurring subgraph candidate report can be generated

## Language and tooling

Recommended stack:
- Python 3.11+
- Pydantic v2
- Typer for CLI
- FastAPI for optional local API
- networkx only if it genuinely simplifies graph ops; otherwise use custom DAG utilities
- pytest
- ruamel.yaml or PyYAML

## Internal packages

Suggested Python package layout:
- `graphsmith/models/`
- `graphsmith/parser/`
- `graphsmith/validator/`
- `graphsmith/runtime/`
- `graphsmith/ops/`
- `graphsmith/registry/`
- `graphsmith/search/`
- `graphsmith/planner/`
- `graphsmith/traces/`
- `graphsmith/cli/`

## Runtime execution model

Execution input:
- skill package path or skill ID
- input payload
- runtime environment capabilities
- optional planner mode

Execution flow:
1. parse skill
2. validate contract + graph
3. compile into execution plan
4. execute nodes in dependency order
5. capture node-level trace
6. return outputs + trace metadata

## Search model

v1 search should support:
- text query over id, name, description, tags
- filter by effects
- filter by input field names
- filter by output field names
- filter by required primitive ops
- filter by version

Embeddings can be an interface only in v1:
- define `EmbeddingProvider`
- default implementation is no-op

## Planner model

The planner receives:
- user goal
- available skills
- constraints
- desired output shape

The planner returns:
- a glue graph referencing existing skills and primitive ops
- unresolved holes if it cannot finish

Important:
- planner output must be validated by the same validator
- unresolved holes are acceptable
- no arbitrary code generation

## Why this architecture

This implementation is intended to test one claim:
reusable typed subgraphs with contracts are a better unit of agent capability than ad hoc tool calls.
