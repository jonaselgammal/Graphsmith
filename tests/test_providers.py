"""Tests for LLM provider abstraction: config, selection, stubs."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from graphsmith.ops.llm_provider import EchoLLMProvider, StubLLMProvider
from graphsmith.ops.providers import (
    AnthropicProvider,
    OpenAICompatibleProvider,
    ProviderConfigError,
    create_provider,
)


# ── factory ──────────────────────────────────────────────────────────


class TestCreateProvider:
    def test_echo(self) -> None:
        p = create_provider("echo")
        assert isinstance(p, EchoLLMProvider)
        assert p.generate("hi") == "hi"  # empty prefix

    def test_unknown_name(self) -> None:
        with pytest.raises(ProviderConfigError, match="Unknown provider"):
            create_provider("magic")

    def test_anthropic_no_key_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GRAPHSMITH_ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ProviderConfigError, match="API key"):
            create_provider("anthropic")

    def test_anthropic_with_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GRAPHSMITH_ANTHROPIC_API_KEY", "sk-test-123")
        p = create_provider("anthropic")
        assert isinstance(p, AnthropicProvider)
        assert p.api_key == "sk-test-123"

    def test_anthropic_with_explicit_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GRAPHSMITH_ANTHROPIC_API_KEY", raising=False)
        p = create_provider("anthropic", api_key="sk-explicit")
        assert p.api_key == "sk-explicit"

    def test_anthropic_custom_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GRAPHSMITH_ANTHROPIC_API_KEY", "sk-test")
        p = create_provider("anthropic", model="claude-haiku-4-5-20251001")
        assert isinstance(p, AnthropicProvider)
        assert p.model == "claude-haiku-4-5-20251001"

    def test_openai_no_key_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GRAPHSMITH_OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GRAPHSMITH_GROQ_API_KEY", raising=False)
        with pytest.raises(ProviderConfigError, match="API key"):
            create_provider("openai")

    def test_openai_with_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GRAPHSMITH_OPENAI_API_KEY", "sk-openai-test")
        p = create_provider("openai")
        assert isinstance(p, OpenAICompatibleProvider)
        assert p.api_key == "sk-openai-test"
        assert "openai.com" in p.base_url

    def test_openai_custom_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GRAPHSMITH_OPENAI_API_KEY", "sk-test")
        p = create_provider("openai", base_url="http://localhost:11434/v1")
        assert isinstance(p, OpenAICompatibleProvider)
        assert p.base_url == "http://localhost:11434/v1"

    def test_openai_custom_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GRAPHSMITH_OPENAI_API_KEY", "sk-test")
        p = create_provider("openai", model="gpt-4o")
        assert p.model == "gpt-4o"


# ── provider config ─────────────────────────────────────────────────


class TestProviderConfig:
    def test_anthropic_env_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GRAPHSMITH_ANTHROPIC_API_KEY", "from-env")
        p = AnthropicProvider()
        assert p.api_key == "from-env"

    def test_anthropic_explicit_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GRAPHSMITH_ANTHROPIC_API_KEY", "from-env")
        p = AnthropicProvider(api_key="explicit")
        assert p.api_key == "explicit"

    def test_openai_env_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GRAPHSMITH_OPENAI_API_KEY", "key")
        monkeypatch.setenv("GRAPHSMITH_OPENAI_BASE_URL", "http://custom:8080/v1")
        p = OpenAICompatibleProvider()
        assert p.base_url == "http://custom:8080/v1"

    def test_openai_default_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GRAPHSMITH_OPENAI_API_KEY", "key")
        monkeypatch.delenv("GRAPHSMITH_OPENAI_BASE_URL", raising=False)
        p = OpenAICompatibleProvider()
        assert "api.openai.com" in p.base_url


# ── CLI provider selection ───────────────────────────────────────────


class TestCLIProviderSelection:
    def test_plan_llm_echo_default(self, tmp_path: Path) -> None:
        """--backend llm defaults to echo provider.

        The prompt contains a JSON example, so the parser extracts it.
        """
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, [
            "plan", "test",
            "--backend", "llm",
            "--registry", str(tmp_path / "reg"),
        ])
        # Parser extracts the example JSON from the echoed prompt
        assert result.exit_code == 0 or "partial" in result.output.lower()

    def test_plan_llm_anthropic_no_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        monkeypatch.delenv("GRAPHSMITH_ANTHROPIC_API_KEY", raising=False)
        result = runner.invoke(app, [
            "plan", "test",
            "--backend", "llm",
            "--provider", "anthropic",
            "--registry", str(tmp_path / "reg"),
        ])
        assert result.exit_code == 1
        assert "API key" in result.output

    def test_plan_llm_openai_no_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        monkeypatch.delenv("GRAPHSMITH_OPENAI_API_KEY", raising=False)
        result = runner.invoke(app, [
            "plan", "test",
            "--backend", "llm",
            "--provider", "openai",
            "--registry", str(tmp_path / "reg"),
        ])
        assert result.exit_code == 1
        assert "API key" in result.output

    def test_plan_mock_backend_ignores_provider(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        from conftest import EXAMPLE_DIR
        runner = CliRunner()
        reg_root = tmp_path / "reg"
        runner.invoke(app, [
            "publish", str(EXAMPLE_DIR / "text.summarize.v1"),
            "--registry", str(reg_root),
        ])
        result = runner.invoke(app, [
            "plan", "summarize",
            "--backend", "mock",
            "--provider", "anthropic",  # should be ignored
            "--registry", str(reg_root),
        ])
        assert result.exit_code == 0
        assert "success" in result.output.lower()


# ── LLM planner backend with stubbed provider ────────────────────────


class TestLLMBackendWithStub:
    def test_canned_json_response(self) -> None:
        """Stub provider returns valid JSON -> success."""
        from graphsmith.planner import LLMPlannerBackend
        from graphsmith.planner.models import PlanRequest
        from graphsmith.registry.index import IndexEntry

        plan_json = json.dumps({
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [{"name": "result", "type": "string"}],
            "nodes": [{"id": "s", "op": "template.render", "config": {"template": "{{text}}"}}],
            "edges": [{"from": "input.text", "to": "s.text"}],
            "graph_outputs": {"result": "s.rendered"},
        })

        class CannedProvider:
            def generate(self, prompt: str, **kw: Any) -> str:
                return plan_json
            def extract(self, prompt: str, schema: dict, **kw: Any) -> dict:
                return {}

        backend = LLMPlannerBackend(provider=CannedProvider())
        request = PlanRequest(
            goal="test",
            candidates=[IndexEntry(id="x", name="X", version="1", description="x")],
        )
        result = backend.compose(request)
        assert result.status == "success"
        assert result.graph is not None


# ── optional smoke tests (skipped unless env vars present) ───────────


@pytest.mark.skipif(
    not os.environ.get("GRAPHSMITH_ANTHROPIC_API_KEY"),
    reason="GRAPHSMITH_ANTHROPIC_API_KEY not set",
)
class TestAnthropicSmoke:
    def test_simple_generate(self) -> None:
        p = AnthropicProvider()
        result = p.generate("Say hello in exactly 3 words.")
        assert isinstance(result, str)
        assert len(result) > 0


@pytest.mark.skipif(
    not os.environ.get("GRAPHSMITH_OPENAI_API_KEY"),
    reason="GRAPHSMITH_OPENAI_API_KEY not set",
)
class TestOpenAISmoke:
    def test_simple_generate(self) -> None:
        p = OpenAICompatibleProvider()
        result = p.generate("Say hello in exactly 3 words.")
        assert isinstance(result, str)
        assert len(result) > 0