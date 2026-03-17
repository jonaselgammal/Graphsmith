# Release Checklist

## Before tagging

- [ ] All tests pass: `pytest`
- [ ] Version is consistent in `pyproject.toml` and `graphsmith/__init__.py`
- [ ] `graphsmith version` shows the correct version
- [ ] README commands work: validate, run, plan, plan-and-run
- [ ] Example workflows doc is accurate
- [ ] CHANGELOG.md is up to date
- [ ] No uncommitted changes

## Optional smoke tests

- [ ] `graphsmith run examples/skills/text.normalize.v1 --input '{"text":"  Hello   World  "}'`
- [ ] `graphsmith run examples/skills/text.summarize.v1 --input '{"text":"test","max_sentences":1}' --mock-llm`
- [ ] Live provider test (if API key available):
      `GRAPHSMITH_ANTHROPIC_API_KEY=... pytest tests/test_live_providers.py -v`

## Tag and release

```bash
git tag v0.2.0
git push origin v0.2.0
```

## Optional: PyPI

```bash
pip install build twine
python -m build
twine upload dist/*
```
