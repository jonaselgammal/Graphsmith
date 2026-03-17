# Agent Task

Implement Sprint 01 for Graphsmith.

## Scope
- models
- parser
- validator
- CLI
- tests

## Validation requirements
The validator must check:
- required files exist
- YAML parses
- required top-level keys exist
- node IDs are unique
- graph is a DAG
- edge references are valid
- outputs are mapped
- primitive ops are recognized
- dependency references exist syntactically
- effect vocabulary is valid

## Out of scope
- registry API
- planner
- promotion
- public website
- automatic embeddings
