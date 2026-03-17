# Instructions for Coding Agents

You are implementing the first version of **Graphsmith**.

Read these files in order:
1. `README.md`
2. `docs/IMPLEMENTATION_PLAN.md`
3. `specs/GRAPHSMITH_SPEC_V1.md`
4. `tasks/SPRINT_01.md`

## Mission

Build a minimal but real system where:
- reusable typed subgraphs can be defined in YAML
- those subgraphs have contracts
- composed graphs can be validated deterministically
- valid graphs can be executed by a deterministic runtime
- execution traces are recorded
- a local registry can publish and search skills

## Constraints

- Prefer Python for v1 implementation.
- Use YAML for skill packages.
- Use Pydantic or dataclasses for internal models.
- Use JSON Schema only for external file validation.
- Keep the runtime deterministic.
- Do not add autonomous code generation or arbitrary Python execution.
- Do not implement unbounded loops.
- Do not add features not justified by the spec.
- Every module must have tests.

## Architecture constraints

### Primitive ops allowed in v1
- template.render
- json.parse
- select.fields
- array.map
- array.filter
- branch.if
- fallback.try
- parallel.map
- assert.check
- llm.generate
- llm.extract
- skill.invoke

### Effects vocabulary
- pure
- llm_inference
- network_read
- network_write
- filesystem_read
- filesystem_write
- memory_read
- memory_write

### Validation requirements
The validator must check:
- schema validity
- unique IDs
- missing references
- missing inputs
- type compatibility
- bounded graph structure
- declared effect compatibility
- skill dependency existence

## Deliverables expected in v1

- parser for `skill.yaml`, `graph.yaml`, `examples.yaml`
- internal IR models
- JSON Schema files
- validator
- deterministic runtime
- local registry API or CLI
- hybrid search stub: keyword + metadata filters; embeddings optional behind interface
- trace writer
- example skills
- tests
- CLI for:
  - validate skill
  - run skill
  - publish skill
  - search skills

## Coding style

- Small modules
- Strong typing
- Clear docstrings
- Structured errors
- No hidden globals
- Avoid framework sprawl

## Important implementation principle

A **Graphsmith** is the reusable unit.
A **glue graph** is a task-specific composition.
Do not publish glue graphs automatically.
