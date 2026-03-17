# Contributing to Graphsmith

Thanks for your interest in contributing.

## Project overview

Graphsmith is a typed, contract-based subgraph standard with a deterministic
runtime, local registry, LLM planner, and execution trace system. See
[README.md](README.md) for the full overview.

## Setup

```bash
# Clone
git clone https://github.com/YOUR_ORG/graphsmith.git
cd graphsmith

# Create a virtual environment (Python 3.11+)
python3 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Verify
graphsmith version
pytest
```

## Running tests

```bash
# All unit tests (no network, no API keys)
pytest

# Verbose
pytest -v

# Single file
pytest tests/test_demo_skills.py -v
```

### Live provider tests

These require API keys and are skipped by default.

```bash
# Anthropic
GRAPHSMITH_ANTHROPIC_API_KEY=sk-ant-... pytest tests/test_live_providers.py -v

# OpenAI
GRAPHSMITH_OPENAI_API_KEY=sk-... pytest tests/test_live_providers.py -v
```

Never commit API keys.

## Coding style

- Python 3.11+
- Type annotations on all public functions
- Small modules — each file has one clear purpose
- No hidden global state (registries, trace stores, providers are always injected)
- Pydantic v2 for data models
- `from __future__ import annotations` in every module
- Tests in `tests/` using pytest

## What to discuss first

Open an issue before submitting a PR for:
- New primitive ops (changes the spec)
- New provider integrations
- Changes to binding or execution semantics
- Registry format changes
- Planner prompt structure changes

These are welcome but benefit from design discussion.

## What's great for direct PRs

- Bug fixes with regression tests
- Documentation improvements
- New example skills
- Test coverage improvements
- Error message improvements
- Typo fixes

## Pull request process

1. Fork and create a branch
2. Make your changes
3. Run `pytest` and ensure all tests pass
4. Submit a PR with a clear description of what and why
