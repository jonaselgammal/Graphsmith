# Sprint 09 — Real LLM Validation and System Polish

## Live tests

### Provider smoke tests (existing, expanded)

| Test | Env var | Validates |
|------|---------|-----------|
| Anthropic generate | `GRAPHSMITH_ANTHROPIC_API_KEY` | Provider call succeeds, returns non-empty string |
| OpenAI generate | `GRAPHSMITH_OPENAI_API_KEY` | Provider call succeeds, returns non-empty string |

### Planner integration tests (new)

| Test | Env var | Validates |
|------|---------|-----------|
| Anthropic plan | `GRAPHSMITH_ANTHROPIC_API_KEY` | Full pipeline: plan → parse → validate. Result is success/partial (not failure). |
| OpenAI plan | `GRAPHSMITH_OPENAI_API_KEY` | Same as above. |
| Anthropic plan-and-run | `GRAPHSMITH_ANTHROPIC_API_KEY` | Plan → validate → execute with mock LLM runtime. Trace produced. |

## Gating

All live tests are gated with `@pytest.mark.skipif` on the relevant
env var. They never run in a standard `pytest` invocation.

To run live tests:
```bash
export GRAPHSMITH_ANTHROPIC_API_KEY=sk-...
pytest tests/test_live_providers.py -v
```

## Success/failure criteria

- **Success**: provider returns a response, parser produces a
  `PlanResult` with status `success` or `partial`, and if a graph
  is produced it passes `validate_skill_package()`.
- **Acceptable partial**: provider returns valid JSON but the graph
  has holes or validation issues. Recorded as `partial`.
- **Failure**: provider error, unparseable response, or crash.
  These are real bugs to investigate.

## Prompt/parser fixes from live testing

Any changes are limited to:
- wording improvements in the prompt
- additional extraction patterns in the parser (deterministic only)
- no provider-specific forks in the parser
- no silent field invention

## CLI polish

| Command | Purpose |
|---------|---------|
| `graphsmith version` | Print version string |
| `graphsmith list-ops` | Print all primitive ops, one per line |

Both produce deterministic output useful for debugging and scripting.

## Explicit limitations

- Live tests may be flaky due to LLM non-determinism
- No retry logic — single-shot only
- No provider benchmarking
- No cost tracking
- Live tests are never required for CI pass
