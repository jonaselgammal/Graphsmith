# Sprint 08A — Provider Architecture

## Provider abstraction

The existing `LLMProvider` Protocol defines the transport contract:

```python
class LLMProvider(Protocol):
    def generate(self, prompt: str, **kwargs) -> str: ...
    def extract(self, prompt: str, schema: dict, **kwargs) -> dict: ...
```

All providers implement this protocol. The planner, runtime, and CLI
are provider-agnostic — they accept any `LLMProvider` instance.

## What belongs where

| Layer | Responsibility |
|-------|---------------|
| **Provider** (transport) | Send prompt to API, return raw text. Handle auth, retries, errors. |
| **Planner backend** | Build prompt, call provider, pass response to parser. |
| **Parser** | Turn raw text into typed `PlanResult`. Provider-agnostic. |
| **CLI** | Select provider from flags/env, inject into backend. |

The parser never sees provider details. The planner backend never
constructs HTTP requests. The CLI never parses LLM output.

## Provider selection

CLI flags:
- `--provider echo` — test double (default, no network)
- `--provider anthropic` — Anthropic Messages API
- `--provider openai` — OpenAI-compatible Chat Completions API

When `--backend llm` is used, `--provider` selects the transport.
When `--backend mock`, `--provider` is ignored (mock planner
doesn't call a provider).

For runtime `llm.generate`/`llm.extract` ops:
- `--mock-llm` uses `EchoLLMProvider` (unchanged)
- `--provider` with `--backend llm` sets the planning provider only
- Runtime and planner providers may differ (the user controls both)

## Env var configuration

| Var | Provider | Required |
|-----|----------|----------|
| `GRAPHSMITH_ANTHROPIC_API_KEY` | anthropic | yes |
| `GRAPHSMITH_OPENAI_API_KEY` | openai | yes |
| `GRAPHSMITH_OPENAI_BASE_URL` | openai | no (default: `https://api.openai.com/v1`) |

If a provider is selected but its API key env var is missing, the
CLI fails immediately with an actionable error.

## AnthropicProvider

- Uses the Anthropic Messages API (`/v1/messages`)
- Sends `system` + `user` message
- Returns `content[0].text`
- Requires `anthropic` package (optional dependency)
- Falls back to `httpx` if `anthropic` package not installed

## OpenAICompatibleProvider

- Uses the OpenAI Chat Completions API (`/v1/chat/completions`)
- Generic enough for OpenAI, Groq, Together, local Ollama, etc.
- Configurable `base_url` and `model`
- Requires `httpx` (added as optional dependency)
- No vendor-specific extensions

## Adding a new provider

1. Create a class implementing `LLMProvider` protocol
2. Add a factory case in `graphsmith.ops.providers.create_provider()`
3. Add env var docs
4. No changes needed to planner, parser, or runtime

## Explicit limitations

- No streaming support
- No retry/backoff logic (single-shot)
- No token counting or budget management
- No provider-specific prompt formatting
- `extract()` uses `generate()` internally for both real providers
  (structured extraction via prompt, not native tool use)
- Smoke tests require env vars and are skipped by default
