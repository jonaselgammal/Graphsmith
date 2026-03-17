"""Real LLM provider implementations and factory.

Providers are transport adapters that implement the LLMProvider protocol.
They handle API communication only — no prompt construction or response parsing.
"""
from __future__ import annotations

import json
import os
from typing import Any

from graphsmith.exceptions import GraphsmithError, ProviderError
from graphsmith.ops.llm_provider import LLMProvider


class ProviderConfigError(GraphsmithError):
    """Raised when provider configuration is missing or invalid."""


# ── Anthropic ────────────────────────────────────────────────────────


class AnthropicProvider:
    """Provider for the Anthropic Messages API.

    Uses httpx directly to avoid a hard dependency on the anthropic package.
    """

    PROVIDER_NAME = "anthropic"
    DEFAULT_MODEL = "claude-sonnet-4-20250514"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> None:
        self.api_key = api_key or os.environ.get("GRAPHSMITH_ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ProviderConfigError(
                "Anthropic API key not found. "
                "Set GRAPHSMITH_ANTHROPIC_API_KEY or pass api_key."
            )
        self.model = model or self.DEFAULT_MODEL
        self.max_tokens = max_tokens
        self._base_url = "https://api.anthropic.com"

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def generate(self, prompt: str, **kwargs: Any) -> str:
        import httpx

        model = kwargs.get("model", self.model)
        system = kwargs.get("system", "")

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "messages": [{"role": "user", "content": prompt}],
        }
        # Anthropic supports a top-level system parameter
        if system:
            body["system"] = system

        resp = httpx.post(
            f"{self._base_url}/v1/messages",
            json=body,
            headers=self._headers(),
            timeout=120.0,
        )
        self._check_response(resp, model=model)
        data = resp.json()
        return data["content"][0]["text"]

    def extract(self, prompt: str, schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        extraction_prompt = (
            f"{prompt}\n\nRespond with a JSON object matching this schema:\n"
            f"{json.dumps(schema, indent=2)}"
        )
        raw = self.generate(extraction_prompt, **kwargs)
        return json.loads(raw)

    def list_models(self) -> list[dict[str, str]]:
        """List available models from the Anthropic Models API."""
        import httpx

        resp = httpx.get(
            f"{self._base_url}/v1/models",
            headers=self._headers(),
            timeout=30.0,
        )
        if resp.status_code != 200:
            # Models API may not be available for all accounts/plans
            raise ProviderError(
                f"Failed to list Anthropic models (HTTP {resp.status_code})",
                provider=self.PROVIDER_NAME,
                status_code=resp.status_code,
                hint="Model listing requires a valid API key. "
                     "Check your account permissions.",
            )
        data = resp.json()
        models = data.get("data", [])
        return [
            {"id": m["id"], "name": m.get("display_name", m["id"])}
            for m in models
        ]

    def _check_response(self, resp: Any, *, model: str) -> None:
        """Parse Anthropic error responses into actionable ProviderError."""
        if resp.status_code < 400:
            return

        # Try to parse Anthropic's structured error body
        try:
            body = resp.json()
            err = body.get("error", {})
            err_type = err.get("type", "unknown_error")
            err_msg = err.get("message", resp.text[:200])
        except Exception:
            err_type = "http_error"
            err_msg = resp.text[:200]

        if err_type == "not_found_error" or resp.status_code == 404:
            raise ProviderError(
                f"Anthropic model '{model}' not found.",
                provider=self.PROVIDER_NAME,
                status_code=resp.status_code,
                hint="Run `graphsmith list-models --provider anthropic` to see available models.\n"
                     f"  Default model: {self.DEFAULT_MODEL}",
            )

        if err_type == "authentication_error" or resp.status_code == 401:
            raise ProviderError(
                "Anthropic authentication failed. Check your API key.",
                provider=self.PROVIDER_NAME,
                status_code=resp.status_code,
            )

        if err_type == "invalid_request_error" or resp.status_code == 400:
            raise ProviderError(
                f"Anthropic request error: {err_msg}",
                provider=self.PROVIDER_NAME,
                status_code=resp.status_code,
            )

        raise ProviderError(
            f"Anthropic API error ({resp.status_code}): {err_msg}",
            provider=self.PROVIDER_NAME,
            status_code=resp.status_code,
        )


# ── OpenAI-compatible ────────────────────────────────────────────────


class OpenAICompatibleProvider:
    """Provider for OpenAI-compatible Chat Completions APIs.

    Works with OpenAI, Groq, Together, local Ollama, and any endpoint
    that implements the `/v1/chat/completions` contract.
    """

    PROVIDER_NAME = "openai"
    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 4096,
    ) -> None:
        self.api_key = api_key or os.environ.get("GRAPHSMITH_OPENAI_API_KEY", "")
        if not self.api_key:
            raise ProviderConfigError(
                "OpenAI API key not found. "
                "Set GRAPHSMITH_OPENAI_API_KEY or pass api_key."
            )
        self.model = model or self.DEFAULT_MODEL
        self.max_tokens = max_tokens
        self.base_url = (
            base_url
            or os.environ.get("GRAPHSMITH_OPENAI_BASE_URL", "")
            or "https://api.openai.com/v1"
        ).rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def generate(self, prompt: str, **kwargs: Any) -> str:
        import httpx

        model = kwargs.get("model", self.model)
        system = kwargs.get("system", "")
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "messages": messages,
        }
        if kwargs.get("json_mode", False):
            body["response_format"] = {"type": "json_object"}

        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            json=body,
            headers=self._headers(),
            timeout=120.0,
        )
        self._check_response(resp, model=model)
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def extract(self, prompt: str, schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        extraction_prompt = (
            f"{prompt}\n\nRespond with a JSON object matching this schema:\n"
            f"{json.dumps(schema, indent=2)}"
        )
        raw = self.generate(extraction_prompt, **kwargs)
        return json.loads(raw)

    def list_models(self) -> list[dict[str, str]]:
        """List available models from the OpenAI-compatible Models API."""
        import httpx

        resp = httpx.get(
            f"{self.base_url}/models",
            headers=self._headers(),
            timeout=30.0,
        )
        if resp.status_code != 200:
            raise ProviderError(
                f"Failed to list models (HTTP {resp.status_code})",
                provider=self.PROVIDER_NAME,
                status_code=resp.status_code,
            )
        data = resp.json()
        models = data.get("data", [])
        return [{"id": m["id"]} for m in models]

    def _check_response(self, resp: Any, *, model: str) -> None:
        """Parse OpenAI-style error responses into actionable ProviderError."""
        if resp.status_code < 400:
            return

        try:
            body = resp.json()
            err = body.get("error", {})
            err_msg = err.get("message", resp.text[:200])
        except Exception:
            err_msg = resp.text[:200]

        if resp.status_code == 404 or "model" in err_msg.lower():
            raise ProviderError(
                f"Model '{model}' not found at {self.base_url}.",
                provider=self.PROVIDER_NAME,
                status_code=resp.status_code,
                hint=f"Run `graphsmith list-models --provider openai` to see available models.\n"
                     f"  Default model: {self.DEFAULT_MODEL}",
            )

        if resp.status_code == 401:
            raise ProviderError(
                "Authentication failed. Check your API key.",
                provider=self.PROVIDER_NAME,
                status_code=resp.status_code,
            )

        raise ProviderError(
            f"API error ({resp.status_code}): {err_msg}",
            provider=self.PROVIDER_NAME,
            status_code=resp.status_code,
        )


# ── Factory ──────────────────────────────────────────────────────────


def create_provider(
    name: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> LLMProvider:
    """Create a provider by name.

    Supported names: echo, anthropic, openai.
    """
    if name == "echo":
        from graphsmith.ops.llm_provider import EchoLLMProvider
        return EchoLLMProvider(prefix="")

    if name == "anthropic":
        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        if model:
            kwargs["model"] = model
        return AnthropicProvider(**kwargs)

    if name == "openai":
        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if model:
            kwargs["model"] = model
        if base_url:
            kwargs["base_url"] = base_url
        return OpenAICompatibleProvider(**kwargs)

    raise ProviderConfigError(
        f"Unknown provider '{name}'. Supported: echo, anthropic, openai"
    )
