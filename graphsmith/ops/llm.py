"""llm.generate and llm.extract ops — delegated to an LLMProvider."""
from __future__ import annotations

from typing import Any

from graphsmith.exceptions import OpError
from graphsmith.ops.llm_provider import LLMProvider


def llm_generate(
    config: dict[str, Any],
    inputs: dict[str, Any],
    *,
    provider: LLMProvider,
) -> dict[str, Any]:
    """Generate text via the LLM provider.

    Inputs:
        prompt (str): The prompt to send.

    Config (optional):
        model (str): Model hint passed through to the provider.
        temperature (float): Sampling temperature.

    Returns:
        {"text": <generated string>}
    """
    prompt = inputs.get("prompt")
    if prompt is None:
        raise OpError("llm.generate requires input 'prompt'")
    if not isinstance(prompt, str):
        raise OpError(f"llm.generate: 'prompt' must be a string, got {type(prompt).__name__}")

    kwargs: dict[str, Any] = {}
    if "model" in config:
        kwargs["model"] = config["model"]
    if "temperature" in config:
        kwargs["temperature"] = config["temperature"]

    text = provider.generate(prompt, **kwargs)
    return {"text": text}


def llm_extract(
    config: dict[str, Any],
    inputs: dict[str, Any],
    *,
    provider: LLMProvider,
) -> dict[str, Any]:
    """Extract structured data via the LLM provider.

    Inputs:
        prompt (str): The prompt to send.

    Config:
        schema (dict): Expected output schema (field names → types).

    Returns:
        {"extracted": <dict>}
    """
    prompt = inputs.get("prompt")
    if prompt is None:
        raise OpError("llm.extract requires input 'prompt'")

    schema = config.get("schema")
    if not schema or not isinstance(schema, dict):
        raise OpError("llm.extract requires config.schema (dict)")

    kwargs: dict[str, Any] = {}
    if "model" in config:
        kwargs["model"] = config["model"]

    extracted = provider.extract(prompt, schema, **kwargs)
    return {"extracted": extracted}
