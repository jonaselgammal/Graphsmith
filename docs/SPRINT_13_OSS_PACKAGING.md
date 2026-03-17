# Sprint 13 — OSS Packaging and CI

## Included

- MIT license
- CONTRIBUTING.md with setup, testing, and contribution guidance
- GitHub Actions CI workflow (Python 3.11 + 3.12, pytest)
- .gitignore cleanup
- py.typed marker
- Packaging metadata polish
- Release checklist document

## CI coverage

- Runs on push to main and on pull requests
- Tests Python 3.11 and 3.12
- Installs `.[dev]` dependencies
- Runs `pytest` (unit tests only, no live provider tests)
- Live provider tests are never run in CI

## Contribution guidance

- How to set up the dev environment
- How to run tests (unit and gated live)
- Coding style expectations (typed, small modules, no hidden globals)
- What to discuss before submitting (new ops, spec changes, provider additions)

## Out of scope

- PyPI publishing (prepared but not executed)
- Signed releases
- Docker packaging
- Homebrew formula
- Security policy (SECURITY.md)
- Issue templates beyond what exists
