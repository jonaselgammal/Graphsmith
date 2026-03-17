# Sprint 08C — Model Discovery and Provider Errors

## Root causes found

1. **Opaque error reporting**: `resp.raise_for_status()` throws an
   `httpx.HTTPStatusError` whose string repr is `Client error '404 Not Found'...`.
   The actual Anthropic error body (e.g. `{"error":{"message":"model: claude-3-5-sonnet"}}`)
   is never extracted or shown to the user.

2. **Anthropic system message mishandling**: The code stuffs the system
   message into the user message content. The Anthropic Messages API
   has a dedicated top-level `system` parameter.

3. **No model validation or discovery**: If you pass a wrong model name
   you get a raw HTTP error, not an actionable suggestion.

## Architecture for model discovery

Model discovery lives in the **provider layer** (`graphsmith/ops/providers.py`).
Each provider may implement an optional `list_models()` method.

```python
def list_models(self) -> list[dict[str, str]]:
    """Return available models. Each dict has at least 'id'."""
```

The CLI exposes this via `graphsmith list-models --provider <name>`.
Providers that don't support listing return an empty list or raise.

## Provider error normalization

Each provider's `generate()` method catches HTTP errors and re-raises
as `ProviderError` with:
- the provider name
- the HTTP status code
- the parsed error message from the API response body
- an actionable hint (e.g. "Run `graphsmith list-models --provider anthropic`")

`ProviderError` is a subclass of `GraphsmithError`, not `ExecutionError`,
so it propagates cleanly through the planner backend to the CLI.

## CLI behavior for invalid model names

When a provider returns a model-not-found error, the CLI shows:

```
FAIL: Anthropic model 'claude-3-5-sonnet' not found.
  Hint: Run `graphsmith list-models --provider anthropic` to see available models.
  Default model: claude-sonnet-4-20250514
```

## Anthropic system message fix

The Anthropic Messages API supports a top-level `system` field.
The provider now uses it correctly instead of jamming system
instructions into the user message.

## Limitations

- Model listing requires a valid API key and network access
- Model listing is always gated behind env vars in tests
- Not all providers support model listing (OpenAI-compatible may not)
- No model alias resolution (e.g. "latest" → specific version)
