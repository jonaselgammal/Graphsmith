"""End-to-end integration test: publish -> plan -> run -> trace -> promote."""
from __future__ import annotations

from pathlib import Path

import pytest

from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.parser import load_skill_package
from graphsmith.planner import MockPlannerBackend, LLMPlannerBackend, compose_plan
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.registry import LocalRegistry
from graphsmith.runtime import run_skill_package
from graphsmith.traces import TraceStore, find_promotion_candidates
from graphsmith.validator import validate_skill_package

from conftest import EXAMPLE_DIR


@pytest.fixture()
def workspace(tmp_path: Path) -> dict:
    """Set up a complete isolated workspace."""
    return {
        "registry": LocalRegistry(root=tmp_path / "registry"),
        "traces": TraceStore(root=tmp_path / "traces"),
        "llm": EchoLLMProvider(prefix=""),
    }


class TestFullWorkflow:
    """Verify that all subsystems compose correctly in a realistic local workflow."""

    def test_publish_plan_run_trace_promote(self, workspace: dict) -> None:
        reg = workspace["registry"]
        store = workspace["traces"]
        llm = workspace["llm"]

        # 1. Publish example skills
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        assert reg.has("text.summarize.v1", "1.0.0")

        # 2. Plan a glue graph
        result = compose_plan("summarize text", reg, MockPlannerBackend())
        assert result.status == "success"
        assert result.graph is not None

        # 3. Validate the planned graph
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)

        # 4. Run the planned graph (it uses skill.invoke -> text.summarize.v1)
        exec_result = run_skill_package(
            pkg,
            {"text": "Cats sleep a lot", "max_sentences": 1},
            llm_provider=llm,
            registry=reg,
        )
        assert exec_result.trace.status == "ok"
        # The mock planner wires the first candidate — check we got outputs
        assert len(exec_result.outputs) > 0

        # 5. Persist the trace
        tid = store.save(exec_result.trace)
        loaded = store.load(tid)
        assert loaded["status"] == "ok"

        # 6. Inspect the trace summary
        summary = store.summarise(tid)
        assert summary["status"] == "ok"
        assert summary["node_count"] >= 1

        # 7. Run again to create a repeated pattern
        exec2 = run_skill_package(
            pkg,
            {"text": "Dogs bark loudly", "max_sentences": 1},
            llm_provider=llm,
            registry=reg,
        )
        store.save(exec2.trace)

        # 8. Generate promotion candidates
        candidates = find_promotion_candidates(store, min_frequency=2)
        assert len(candidates) >= 1
        assert candidates[0].frequency >= 2


class TestLLMPlannerBackendInterface:
    """Verify the LLM planner backend works through the pipeline."""

    def test_llm_backend_echo_extracts_example(self, workspace: dict) -> None:
        """Echo returns the prompt which contains a JSON example.

        The improved parser extracts the first JSON block from the prompt,
        which happens to be the example from the output contract. This
        produces a parseable (if semantically wrong) result.
        """
        reg = workspace["registry"]
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")

        llm = EchoLLMProvider(prefix="")
        backend = LLMPlannerBackend(provider=llm)
        result = compose_plan("summarize text", reg, backend)

        # The prompt contains a valid JSON example, so parsing succeeds
        # (the plan may not match the actual goal, but it's structurally valid)
        assert result.status in ("success", "partial")

    def test_llm_backend_with_empty_registry(self, workspace: dict) -> None:
        """Even with empty registry, echo returns prompt with JSON example."""
        reg = workspace["registry"]
        llm = EchoLLMProvider()
        backend = LLMPlannerBackend(provider=llm)
        result = compose_plan("something", reg, backend)
        # Parser extracts the example JSON from the prompt
        assert result.status in ("success", "partial")
