# Sprint 01 — Spec, Parser, Validator

## Goal
Create the first working package parser and deterministic validator.

## Deliverables
- Python package scaffold
- YAML parser
- Pydantic models
- JSON Schema files
- validation CLI
- example skills
- unit tests

## Work items

### 1. Project scaffold
Create:
- `pyproject.toml`
- `graphsmith/`
- `tests/`
- `examples/`
- `schemas/`

### 2. Models
Implement models for:
- Skill metadata
- Input/output fields
- Graph nodes
- Graph edges
- Graph outputs
- Example cases

### 3. Parser
Implement:
- `load_skill_package(path) -> SkillPackage`

### 4. Validator
Implement checks for:
- required files exist
- valid YAML structure
- unique node IDs
- valid address references
- DAG constraint
- required output mappings
- primitive op existence
- dependency references
- type compatibility stub
- effect vocabulary validity

### 5. CLI
Commands:
- `graphsmith validate <path>`
- `graphsmith inspect <path>`

### 6. Tests
Add:
- valid example passes
- duplicate node IDs fail
- cycle fails
- missing output mapping fails
- invalid op fails

## Definition of done
A user can run:
```bash
graphsmith validate examples/skills/text.summarize.v1
```
and receive a clean success message.
