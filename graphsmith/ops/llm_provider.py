"""LLM provider interface and default stub."""
from __future__ import annotations

from typing import Any, Protocol


class LLMProvider(Protocol):
    """Interface for LLM backends.

    Implementations must be stateless per call. The runtime passes this
    through so that tests can inject a mock and production code can plug
    in a real API client.
    """

    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text from a prompt. Returns the generated string."""
        ...

    def extract(self, prompt: str, schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Extract structured data from text according to *schema*."""
        ...


class StubLLMProvider:
    """Default provider that raises to make missing configuration obvious."""

    def generate(self, prompt: str, **kwargs: Any) -> str:
        raise NotImplementedError(
            "No LLM provider configured. Pass an LLMProvider to the executor."
        )

    def extract(self, prompt: str, schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError(
            "No LLM provider configured. Pass an LLMProvider to the executor."
        )


class EchoLLMProvider:
    """Test double that echoes the prompt back (optionally with a prefix)."""

    def __init__(self, prefix: str = "[mock] ") -> None:
        self.prefix = prefix

    def generate(self, prompt: str, **kwargs: Any) -> str:
        return f"{self.prefix}{prompt}"

    def extract(self, prompt: str, schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {k: f"{self.prefix}{k}" for k in schema}
