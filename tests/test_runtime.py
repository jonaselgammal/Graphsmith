"""Tests for the runtime executor and planner."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from graphsmith.exceptions import ExecutionError
from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.parser import load_skill_package
from graphsmith.runtime import run_skill_package, topological_order
from graphsmith.validator import validate_skill_package

from conftest import minimal_examples, minimal_graph, minimal_skill, write_package


# ── helpers ──────────────────────────────────────────────────────────


def _load_and_validate(path: Path):
    pkg = load_skill_package(path)
    validate_skill_package(pkg)
    return pkg


# ── topological planner ─────────────────────────────────────────────


class TestTopologicalOrder:
    def test_summarize_order(self, summarize_path: Path) -> None:
        pkg = load_skill_package(summarize_path)
        order = topological_order(pkg)
        assert order == ["prompt", "summarize"]

    def test_minimal_order(self, tmp_path: Path) -> None:
        write_package(
            tmp_path / "pkg",
            skill=minimal_skill(),
            graph=minimal_graph(),
            examples=minimal_examples(),
        )
        pkg = load_skill_package(tmp_path / "pkg")
        order = topological_order(pkg)
        assert order == ["step"]


# ── end-to-end execution ────────────────────────────────────────────


class TestRunSummarize:
    """End-to-end test for examples/skills/text.summarize.v1."""

    def test_success(self, summarize_path: Path) -> None:
        pkg = _load_and_validate(summarize_path)
        provider = EchoLLMProvider(prefix="")
        result = run_skill_package(
            pkg,
            {"text": "Cats sleep a lot", "max_sentences": 1},
            llm_provider=provider,
        )
        assert "summary" in result.outputs
        # The echo provider returns the prompt as-is
        assert "Cats sleep a lot" in result.outputs["summary"]
        assert result.trace.status == "ok"
        assert len(result.trace.nodes) == 2

    def test_trace_structure(self, summarize_path: Path) -> None:
        pkg = _load_and_validate(summarize_path)
        provider = EchoLLMProvider()
        result = run_skill_package(
            pkg,
            {"text": "hello", "max_sentences": 2},
            llm_provider=provider,
        )
        trace = result.trace.to_dict()
        assert trace["skill_id"] == "text.summarize.v1"
        assert trace["status"] == "ok"
        assert trace["started_at"] < trace["ended_at"]
        for node_trace in trace["nodes"]:
            assert "node_id" in node_trace
            assert "op" in node_trace
            assert node_trace["status"] == "ok"
            assert "started_at" in node_trace
            assert "ended_at" in node_trace

    def test_missing_llm_provider(self, summarize_path: Path) -> None:
        """Without an LLM provider the stub raises NotImplementedError."""
        pkg = _load_and_validate(summarize_path)
        with pytest.raises(ExecutionError, match="No LLM provider"):
            run_skill_package(pkg, {"text": "x", "max_sentences": 1})


class TestRunMinimal:
    """Run the minimal template-only package."""

    def test_template_only(self, tmp_path: Path) -> None:
        write_package(
            tmp_path / "pkg",
            skill=minimal_skill(),
            graph=minimal_graph(),
            examples=minimal_examples(),
        )
        pkg = _load_and_validate(tmp_path / "pkg")
        result = run_skill_package(pkg, {"text": "hello"})
        assert result.outputs == {"result": "hello"}
        assert result.trace.status == "ok"


# ── error cases ──────────────────────────────────────────────────────


class TestRuntimeErrors:
    def test_missing_required_input_at_runtime(self, tmp_path: Path) -> None:
        """Graph expects 'text' but we don't provide it."""
        write_package(
            tmp_path / "pkg",
            skill=minimal_skill(),
            graph=minimal_graph(),
            examples=minimal_examples(),
        )
        pkg = _load_and_validate(tmp_path / "pkg")
        with pytest.raises(ExecutionError, match="not provided"):
            run_skill_package(pkg, {})

    def test_assert_failure_propagates(self, tmp_path: Path) -> None:
        skill = minimal_skill()
        graph = {
            "version": 1,
            "nodes": [
                {
                    "id": "guard",
                    "op": "assert.check",
                    "config": {"message": "text too short"},
                },
                {
                    "id": "step",
                    "op": "template.render",
                    "config": {"template": "{{text}}"},
                },
            ],
            "edges": [
                {"from": "input.text", "to": "guard.condition"},
                {"from": "input.text", "to": "step.text"},
            ],
            "outputs": {"result": "step.rendered"},
        }
        write_package(
            tmp_path / "pkg",
            skill=skill,
            graph=graph,
            examples=minimal_examples(),
        )
        pkg = _load_and_validate(tmp_path / "pkg")
        # Empty string is falsy → assert.check should fail
        with pytest.raises(ExecutionError, match="text too short"):
            run_skill_package(pkg, {"text": ""})

    def test_conflicting_bindings(self, tmp_path: Path) -> None:
        """Edge and node.inputs both bind the same port with different addresses."""
        skill = {
            "id": "test.conflict.v1",
            "name": "Conflict",
            "version": "1.0.0",
            "description": "Test conflict.",
            "inputs": [
                {"name": "a", "type": "string", "required": True},
                {"name": "b", "type": "string", "required": True},
            ],
            "outputs": [{"name": "result", "type": "string"}],
            "effects": ["pure"],
        }
        graph = {
            "version": 1,
            "nodes": [
                {
                    "id": "step",
                    "op": "template.render",
                    "config": {"template": "{{text}}"},
                    "inputs": {"text": "input.b"},  # binds port 'text' to input.b
                },
            ],
            "edges": [
                {"from": "input.a", "to": "step.text"},  # also binds port 'text' to input.a
            ],
            "outputs": {"result": "step.rendered"},
        }
        write_package(
            tmp_path / "pkg",
            skill=skill,
            graph=graph,
            examples=minimal_examples(),
        )
        pkg = load_skill_package(tmp_path / "pkg")
        with pytest.raises(ExecutionError, match="Conflicting bindings"):
            run_skill_package(pkg, {"a": "A", "b": "B"})


# ── multi-node graph ────────────────────────────────────────────────


class TestMultiNodeGraph:
    def test_two_templates_chained(self, tmp_path: Path) -> None:
        """first node renders, second node uses the first's output."""
        skill = {
            "id": "test.chain.v1",
            "name": "Chain",
            "version": "1.0.0",
            "description": "Two templates chained.",
            "inputs": [{"name": "name", "type": "string", "required": True}],
            "outputs": [{"name": "result", "type": "string"}],
            "effects": ["pure"],
        }
        graph = {
            "version": 1,
            "nodes": [
                {
                    "id": "greet",
                    "op": "template.render",
                    "config": {"template": "Hello, {{name}}"},
                },
                {
                    "id": "wrap",
                    "op": "template.render",
                    "config": {"template": "[{{msg}}]"},
                },
            ],
            "edges": [
                {"from": "input.name", "to": "greet.name"},
                {"from": "greet.rendered", "to": "wrap.msg"},
            ],
            "outputs": {"result": "wrap.rendered"},
        }
        examples = {"examples": [{"name": "ex", "input": {"name": "Alice"}}]}
        write_package(tmp_path / "pkg", skill=skill, graph=graph, examples=examples)
        pkg = _load_and_validate(tmp_path / "pkg")
        result = run_skill_package(pkg, {"name": "Alice"})
        assert result.outputs == {"result": "[Hello, Alice]"}
        assert len(result.trace.nodes) == 2
        assert result.trace.nodes[0].node_id == "greet"
        assert result.trace.nodes[1].node_id == "wrap"
