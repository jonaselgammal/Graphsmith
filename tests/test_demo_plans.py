"""Tests for saved demo plans — ensures the canonical demo is always reproducible."""
from __future__ import annotations

from pathlib import Path

import pytest

from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.planner import load_plan, run_glue_graph
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.registry import LocalRegistry
from graphsmith.validator import validate_skill_package

from conftest import EXAMPLE_DIR

PLANS_DIR = Path(__file__).resolve().parent.parent / "examples" / "plans"


@pytest.fixture()
def reg(tmp_path: Path) -> LocalRegistry:
    r = LocalRegistry(root=tmp_path / "reg")
    r.publish(EXAMPLE_DIR / "text.normalize.v1")
    r.publish(EXAMPLE_DIR / "text.extract_keywords.v1")
    r.publish(EXAMPLE_DIR / "text.summarize.v1")
    return r


class TestNormalizeExtractKeywordsPlan:
    plan_path = PLANS_DIR / "normalize_extract_keywords.json"

    def test_loads(self) -> None:
        glue = load_plan(self.plan_path)
        assert glue.goal == "Normalize text and extract keywords"
        assert len(glue.graph.nodes) == 2

    def test_validates(self) -> None:
        glue = load_plan(self.plan_path)
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

    def test_executes(self, reg: LocalRegistry) -> None:
        glue = load_plan(self.plan_path)
        result = run_glue_graph(
            glue,
            {"text": "  AI   agents ARE transforming  SOFTWARE  "},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=reg,
        )
        assert result.trace.status == "ok"
        assert result.outputs["normalized"] == "ai agents are transforming software"
        assert "keywords" in result.outputs
        assert "ai agents are transforming software" in result.outputs["keywords"]

    def test_output_keys(self, reg: LocalRegistry) -> None:
        glue = load_plan(self.plan_path)
        result = run_glue_graph(
            glue, {"text": "hello"}, llm_provider=EchoLLMProvider(prefix=""), registry=reg,
        )
        assert set(result.outputs.keys()) == {"normalized", "keywords"}


class TestNormalizeSummarizeKeywordsPlan:
    plan_path = PLANS_DIR / "normalize_summarize_keywords.json"

    def test_loads(self) -> None:
        glue = load_plan(self.plan_path)
        assert len(glue.graph.nodes) == 3

    def test_validates(self) -> None:
        glue = load_plan(self.plan_path)
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

    def test_executes(self, reg: LocalRegistry) -> None:
        glue = load_plan(self.plan_path)
        result = run_glue_graph(
            glue,
            {"text": "  Cats SLEEP a lot  "},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=reg,
        )
        assert result.trace.status == "ok"
        assert result.outputs["normalized"] == "cats sleep a lot"
        assert "cats sleep a lot" in result.outputs["summary"]
        assert "cats sleep a lot" in result.outputs["keywords"]

    def test_output_keys(self, reg: LocalRegistry) -> None:
        glue = load_plan(self.plan_path)
        result = run_glue_graph(
            glue, {"text": "test"}, llm_provider=EchoLLMProvider(prefix=""), registry=reg,
        )
        assert set(result.outputs.keys()) == {"normalized", "summary", "keywords"}

    def test_three_traces(self, reg: LocalRegistry) -> None:
        glue = load_plan(self.plan_path)
        result = run_glue_graph(
            glue, {"text": "test"}, llm_provider=EchoLLMProvider(prefix=""), registry=reg,
        )
        assert len(result.trace.nodes) == 3
        for node in result.trace.nodes:
            assert node.child_trace is not None
