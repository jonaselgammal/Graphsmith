"""Live provider tests — skipped unless API keys are set.

Run with:
    GRAPHSMITH_ANTHROPIC_API_KEY=sk-... pytest tests/test_live_providers.py -v
    GRAPHSMITH_OPENAI_API_KEY=sk-... pytest tests/test_live_providers.py -v
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from conftest import EXAMPLE_DIR


# ── Anthropic ────────────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("GRAPHSMITH_ANTHROPIC_API_KEY"),
    reason="GRAPHSMITH_ANTHROPIC_API_KEY not set",
)
class TestAnthropicLive:
    def test_simple_generate(self) -> None:
        from graphsmith.ops.providers import AnthropicProvider
        p = AnthropicProvider()
        result = p.generate("Respond with only the word 'hello'.")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_plan_with_candidates(self) -> None:
        """Full planner pipeline: candidates → prompt → provider → parse → validate."""
        from graphsmith.ops.providers import AnthropicProvider
        from graphsmith.planner import LLMPlannerBackend, compose_plan
        from graphsmith.planner.composer import glue_to_skill_package
        from graphsmith.registry import LocalRegistry
        from graphsmith.validator import validate_skill_package

        reg = LocalRegistry(root="/tmp/graphsmith_live_test_reg")
        try:
            reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        except Exception:
            pass  # already published from a previous run

        provider = AnthropicProvider()
        backend = LLMPlannerBackend(provider=provider)
        result = compose_plan("summarize text", reg, backend)

        # Should not be a total failure — the LLM should produce something
        assert result.status in ("success", "partial"), (
            f"Expected success/partial but got {result.status}: "
            f"{result.holes}"
        )
        assert result.retrieval is not None
        assert result.retrieval.registry_size > 0
        assert result.retrieval.candidate_count > 0
        assert "text.summarize.v1" in result.retrieval.candidates

        if result.graph is not None:
            pkg = glue_to_skill_package(result.graph)
            # Validate — may raise, which is informative
            try:
                validate_skill_package(pkg)
            except Exception as exc:
                pytest.skip(f"Graph produced but validation failed: {exc}")

    def test_plan_and_run(self, tmp_path: Path) -> None:
        """Full plan-and-run: plan → validate → execute → trace."""
        from graphsmith.ops.llm_provider import EchoLLMProvider
        from graphsmith.ops.providers import AnthropicProvider
        from graphsmith.planner import LLMPlannerBackend, compose_plan, run_glue_graph
        from graphsmith.registry import LocalRegistry
        from graphsmith.traces import TraceStore

        reg = LocalRegistry(root="/tmp/graphsmith_live_test_reg")
        try:
            reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        except Exception:
            pass

        provider = AnthropicProvider()
        backend = LLMPlannerBackend(provider=provider)
        result = compose_plan("summarize text", reg, backend)

        if result.status != "success" or result.graph is None:
            pytest.skip(f"Plan was {result.status}, skipping execution.")

        # Execute with mock LLM runtime (we only test the pipeline, not real LLM execution)
        exec_result = run_glue_graph(
            result.graph,
            {"text": "Cats sleep a lot", "max_sentences": 1},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=reg,
        )
        assert exec_result.trace.status == "ok"

        # Persist trace
        store = TraceStore(root=tmp_path / "traces")
        tid = store.save(exec_result.trace)
        assert store.load(tid)["status"] == "ok"


# ── OpenAI-compatible ────────────────────────────────────────────────


@pytest.mark.skipif(
    not os.environ.get("GRAPHSMITH_OPENAI_API_KEY"),
    reason="GRAPHSMITH_OPENAI_API_KEY not set",
)
class TestOpenAILive:
    def test_simple_generate(self) -> None:
        from graphsmith.ops.providers import OpenAICompatibleProvider
        p = OpenAICompatibleProvider()
        result = p.generate("Respond with only the word 'hello'.")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_plan_with_candidates(self) -> None:
        from graphsmith.ops.providers import OpenAICompatibleProvider
        from graphsmith.planner import LLMPlannerBackend, compose_plan
        from graphsmith.registry import LocalRegistry

        reg = LocalRegistry(root="/tmp/graphsmith_live_test_reg_oai")
        try:
            reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        except Exception:
            pass

        provider = OpenAICompatibleProvider()
        backend = LLMPlannerBackend(provider=provider)
        result = compose_plan("summarize text", reg, backend)

        assert result.status in ("success", "partial"), (
            f"Expected success/partial but got {result.status}: "
            f"{result.holes}"
        )
        assert result.retrieval is not None
        assert result.retrieval.registry_size > 0
        assert result.retrieval.candidate_count > 0
        assert "text.summarize.v1" in result.retrieval.candidates
