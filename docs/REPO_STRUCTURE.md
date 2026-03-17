# Proposed Graphsmith Repository Structure

Start with a single repo named `graphsmith`.

As the project grows, split it into:

- `graphsmith` — umbrella repo or main monorepo
- `graphsmith-spec` — package format, schemas, standards
- `graphsmith-runtime` — validator, compiler, executor
- `graphsmith-registry` — local/public registry and search
- `graphsmith-web` — public website and browsing UI

## Recommended initial monorepo layout

- `graphsmith/` — Python package
- `tests/`
- `examples/`
- `docs/`
- `schemas/`
- `specs/`
- `tasks/`
- `prompts/`

## Agent guidance

Until the project proves itself, keep everything in one repo.
The agent should preserve modular boundaries so later extraction into
`graphsmith-spec`, `graphsmith-runtime`, and `graphsmith-registry` is easy.
