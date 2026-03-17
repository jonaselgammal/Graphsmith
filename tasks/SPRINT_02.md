# Sprint 02 — Runtime Core

## Goal
Execute valid Graphsmiths deterministically.

## Deliverables
- execution planner
- primitive op implementations
- nested skill invocation
- trace capture
- run CLI
- tests

## Primitive ops to implement first
- template.render
- json.parse
- select.fields
- assert.check
- llm.generate
- skill.invoke

## CLI
- `graphsmith run <path> --input input.json`

## Definition of done
The summarize example runs end-to-end with a mock LLM adapter.
