"""Tests for provider error handling, model discovery, and CLI UX."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from graphsmith.exceptions import ProviderError
from graphsmith.ops.providers import (
    AnthropicProvider,
    OpenAICompatibleProvider,
    ProviderConfigError,
    create_provider,
)


# ── Anthropic error parsing ──────────────────────────────────────────


class TestAnthropicErrorParsing:
    @pytest.fixture()
    def provider(self, monkeypatch: pytest.MonkeyPatch) -> AnthropicProvider:
        monkeypatch.setenv("GRAPHSMITH_ANTHROPIC_API_KEY", "sk-test")
        return AnthropicProvider()

    def test_model_not_found_error(self, provider: AnthropicProvider) -> None:
        """Simulate a 404 with Anthropic's error body."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {
            "type": "error",
            "error": {
                "type": "not_found_error",
                "message": "model: claude-3-5-sonnet",
            },
        }
        with pytest.raises(ProviderError) as exc_info:
            provider._check_response(mock_resp, model="claude-3-5-sonnet")
        err = exc_info.value
        assert "not found" in str(err).lower()
        assert "claude-3-5-sonnet" in str(err)
        assert "list-models" in err.hint
        assert err.status_code == 404
        assert err.provider == "anthropic"

    def test_auth_error(self, provider: AnthropicProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {
            "type": "error",
            "error": {
                "type": "authentication_error",
                "message": "invalid x-api-key",
            },
        }
        with pytest.raises(ProviderError, match="authentication"):
            provider._check_response(mock_resp, model="any")

    def test_invalid_request_error(self, provider: AnthropicProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "max_tokens must be positive",
            },
        }
        with pytest.raises(ProviderError, match="max_tokens"):
            provider._check_response(mock_resp, model="any")

    def test_success_no_error(self, provider: AnthropicProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        provider._check_response(mock_resp, model="any")  # should not raise

    def test_generic_server_error(self, provider: AnthropicProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {
            "type": "error",
            "error": {"type": "server_error", "message": "internal"},
        }
        with pytest.raises(ProviderError, match="500"):
            provider._check_response(mock_resp, model="any")


# ── OpenAI error parsing ─────────────────────────────────────────────


class TestOpenAIErrorParsing:
    @pytest.fixture()
    def provider(self, monkeypatch: pytest.MonkeyPatch) -> OpenAICompatibleProvider:
        monkeypatch.setenv("GRAPHSMITH_OPENAI_API_KEY", "sk-test")
        return OpenAICompatibleProvider()

    def test_model_not_found(self, provider: OpenAICompatibleProvider) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {
            "error": {"message": "The model 'bad-model' does not exist"},
        }
        with pytest.raises(ProviderError) as exc_info:
            provider._check_response(mock_resp, model="bad-model")
        assert "not found" in str(exc_info.value).lower()
        assert "list-models" in exc_info.value.hint


# ── ProviderError model ──────────────────────────────────────────────


class TestProviderErrorModel:
    def test_fields(self) -> None:
        err = ProviderError(
            "Model not found",
            provider="anthropic",
            status_code=404,
            hint="Try list-models",
        )
        assert err.provider == "anthropic"
        assert err.status_code == 404
        assert "Try list-models" in str(err)

    def test_no_hint(self) -> None:
        err = ProviderError("Something failed", provider="openai")
        assert "Something failed" in str(err)
        assert err.hint == ""


# ── CLI list-models ──────────────────────────────────────────────────


class TestCLIListModels:
    def test_echo_provider(self) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["list-models", "--provider", "echo"])
        assert result.exit_code == 0
        assert "echo" in result.output

    def test_no_api_key_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        monkeypatch.delenv("GRAPHSMITH_ANTHROPIC_API_KEY", raising=False)
        result = runner.invoke(app, ["list-models", "--provider", "anthropic"])
        assert result.exit_code == 1
        assert "API key" in result.output

    def test_mocked_anthropic_models(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock the list_models method to return fake model list."""
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        monkeypatch.setenv("GRAPHSMITH_ANTHROPIC_API_KEY", "sk-test")

        fake_models = [
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
            {"id": "claude-haiku-4-5-20251001", "name": "Claude Haiku 4.5"},
        ]

        with patch.object(AnthropicProvider, "list_models", return_value=fake_models):
            result = runner.invoke(app, ["list-models", "--provider", "anthropic"])

        assert result.exit_code == 0
        assert "claude-sonnet-4-20250514" in result.output
        assert "claude-haiku-4-5-20251001" in result.output


# ── CLI plan with invalid model ──────────────────────────────────────


class TestCLIPlanInvalidModel:
    def test_plan_with_invalid_model_shows_hint(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When Anthropic returns 404 for a model, CLI shows actionable error."""
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        from conftest import EXAMPLE_DIR
        runner = CliRunner()

        reg_root = tmp_path / "reg"
        runner.invoke(app, [
            "publish", str(EXAMPLE_DIR / "text.summarize.v1"),
            "--registry", str(reg_root),
        ])

        monkeypatch.setenv("GRAPHSMITH_ANTHROPIC_API_KEY", "sk-test")

        # Mock generate to raise ProviderError (simulating what _check_response does)
        def mock_generate(self, prompt, **kwargs):
            raise ProviderError(
                "Anthropic model 'bad-model-name' not found.",
                provider="anthropic",
                status_code=404,
                hint="Run `graphsmith list-models --provider anthropic`",
            )

        with patch.object(AnthropicProvider, "generate", mock_generate):
            result = runner.invoke(app, [
                "plan", "summarize",
                "--backend", "llm",
                "--provider", "anthropic",
                "--model", "bad-model-name",
                "--registry", str(reg_root),
            ])

        assert result.exit_code == 1
        output = result.output.lower()
        assert "not found" in output or "fail" in output


# ── gated live model listing ─────────────────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("GRAPHSMITH_ANTHROPIC_API_KEY"),
    reason="GRAPHSMITH_ANTHROPIC_API_KEY not set",
)
class TestAnthropicLiveModelListing:
    def test_list_models(self) -> None:
        p = AnthropicProvider()
        models = p.list_models()
        assert len(models) > 0
        ids = [m["id"] for m in models]
        # Should have at least one claude model
        assert any("claude" in mid for mid in ids)

    def test_cli_list_models(self) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["list-models", "--provider", "anthropic"])
        assert result.exit_code == 0
        assert "claude" in result.output.lower()
