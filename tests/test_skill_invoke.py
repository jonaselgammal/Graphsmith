"""Tests for skill.invoke op and recursive execution."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from graphsmith.exceptions import ExecutionError
from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.parser import load_skill_package
from graphsmith.registry import LocalRegistry
from graphsmith.runtime import run_skill_package
from graphsmith.validator import validate_skill_package

from conftest import (
    EXAMPLE_DIR,
    minimal_examples,
    minimal_graph,
    minimal_skill,
    write_package,
)


@pytest.fixture()
def reg(tmp_path: Path) -> LocalRegistry:
    return LocalRegistry(root=tmp_path / "registry")


def _make_invoker_package(
    root: Path,
    *,
    target_id: str,
    target_version: str,
) -> Path:
    """Create a skill that invokes another skill via skill.invoke.

    The invoker expects input 'text' and outputs 'result'.
    The target skill must also accept 'text' and output 'result'.
    """
    skill = {
        "id": "test.invoker.v1",
        "name": "Invoker",
        "version": "1.0.0",
        "description": "Invokes a sub-skill.",
        "inputs": [{"name": "text", "type": "string", "required": True}],
        "outputs": [{"name": "result", "type": "string"}],
        "effects": ["pure"],
        "dependencies": [target_id],
    }
    graph = {
        "version": 1,
        "nodes": [
            {
                "id": "call",
                "op": "skill.invoke",
                "config": {
                    "skill_id": target_id,
                    "version": target_version,
                },
            },
        ],
        "edges": [
            {"from": "input.text", "to": "call.text"},
        ],
        "outputs": {"result": "call.result"},
    }
    examples = {"examples": [{"name": "ex", "input": {"text": "hi"}}]}
    return write_package(root, skill=skill, graph=graph, examples=examples)


# ── basic skill.invoke ───────────────────────────────────────────────


class TestSkillInvoke:
    def test_invoke_published_skill(
        self, reg: LocalRegistry, tmp_path: Path
    ) -> None:
        # Publish a simple target skill
        target_dir = tmp_path / "target"
        write_package(
            target_dir,
            skill=minimal_skill(),
            graph=minimal_graph(),
            examples=minimal_examples(),
        )
        reg.publish(target_dir)

        # Create invoker
        invoker_dir = _make_invoker_package(
            tmp_path / "invoker",
            target_id="test.minimal.v1",
            target_version="1.0.0",
        )
        pkg = load_skill_package(invoker_dir)
        validate_skill_package(pkg)

        result = run_skill_package(
            pkg, {"text": "hello"}, registry=reg,
        )
        assert result.outputs == {"result": "hello"}
        assert result.trace.status == "ok"

    def test_invoke_trace_has_child(
        self, reg: LocalRegistry, tmp_path: Path
    ) -> None:
        target_dir = tmp_path / "target"
        write_package(
            target_dir,
            skill=minimal_skill(),
            graph=minimal_graph(),
            examples=minimal_examples(),
        )
        reg.publish(target_dir)

        invoker_dir = _make_invoker_package(
            tmp_path / "invoker",
            target_id="test.minimal.v1",
            target_version="1.0.0",
        )
        pkg = load_skill_package(invoker_dir)
        validate_skill_package(pkg)

        result = run_skill_package(pkg, {"text": "hi"}, registry=reg)
        # The call node should have a child trace
        call_trace = result.trace.nodes[0]
        assert call_trace.node_id == "call"
        assert call_trace.child_trace is not None
        assert call_trace.child_trace.skill_id == "test.minimal.v1"
        assert call_trace.child_trace.status == "ok"

    def test_invoke_with_llm_sub_skill(
        self, reg: LocalRegistry, tmp_path: Path
    ) -> None:
        """Invoke text.summarize.v1 which uses llm.generate."""
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")

        # Create an invoker that calls summarize
        skill = {
            "id": "test.sum_invoker.v1",
            "name": "Summarizer Invoker",
            "version": "1.0.0",
            "description": "Invokes summarize.",
            "inputs": [
                {"name": "text", "type": "string", "required": True},
                {"name": "max_sentences", "type": "integer", "required": True},
            ],
            "outputs": [{"name": "summary", "type": "string"}],
            "effects": ["llm_inference"],
        }
        graph = {
            "version": 1,
            "nodes": [
                {
                    "id": "call",
                    "op": "skill.invoke",
                    "config": {
                        "skill_id": "text.summarize.v1",
                        "version": "1.0.0",
                    },
                },
            ],
            "edges": [
                {"from": "input.text", "to": "call.text"},
                {"from": "input.max_sentences", "to": "call.max_sentences"},
            ],
            "outputs": {"summary": "call.summary"},
        }
        invoker_dir = tmp_path / "invoker"
        write_package(
            invoker_dir, skill=skill, graph=graph,
            examples={"examples": [{"name": "ex", "input": {"text": "x", "max_sentences": 1}}]},
        )
        pkg = load_skill_package(invoker_dir)
        validate_skill_package(pkg)

        provider = EchoLLMProvider(prefix="")
        result = run_skill_package(
            pkg,
            {"text": "Cats sleep a lot", "max_sentences": 1},
            llm_provider=provider,
            registry=reg,
        )
        assert "summary" in result.outputs
        assert "Cats sleep a lot" in result.outputs["summary"]


# ── error cases ──────────────────────────────────────────────────────


class TestSkillInvokeErrors:
    def test_invoke_missing_skill_id(
        self, reg: LocalRegistry, tmp_path: Path
    ) -> None:
        skill = minimal_skill()
        graph = {
            "version": 1,
            "nodes": [
                {"id": "call", "op": "skill.invoke", "config": {}},
            ],
            "edges": [{"from": "input.text", "to": "call.text"}],
            "outputs": {"result": "call.result"},
        }
        write_package(
            tmp_path / "pkg",
            skill=skill, graph=graph, examples=minimal_examples(),
        )
        pkg = load_skill_package(tmp_path / "pkg")
        with pytest.raises(ExecutionError, match="skill_id"):
            run_skill_package(pkg, {"text": "x"}, registry=reg)

    def test_invoke_missing_version(
        self, reg: LocalRegistry, tmp_path: Path
    ) -> None:
        skill = minimal_skill()
        graph = {
            "version": 1,
            "nodes": [
                {
                    "id": "call",
                    "op": "skill.invoke",
                    "config": {"skill_id": "test.minimal.v1"},
                },
            ],
            "edges": [{"from": "input.text", "to": "call.text"}],
            "outputs": {"result": "call.result"},
        }
        write_package(
            tmp_path / "pkg",
            skill=skill, graph=graph, examples=minimal_examples(),
        )
        pkg = load_skill_package(tmp_path / "pkg")
        with pytest.raises(ExecutionError, match="version"):
            run_skill_package(pkg, {"text": "x"}, registry=reg)

    def test_invoke_skill_not_in_registry(
        self, reg: LocalRegistry, tmp_path: Path
    ) -> None:
        invoker_dir = _make_invoker_package(
            tmp_path / "invoker",
            target_id="nonexistent.v1",
            target_version="1.0.0",
        )
        pkg = load_skill_package(invoker_dir)
        with pytest.raises(ExecutionError, match="not found"):
            run_skill_package(pkg, {"text": "x"}, registry=reg)

    def test_invoke_no_registry(self, tmp_path: Path) -> None:
        invoker_dir = _make_invoker_package(
            tmp_path / "invoker",
            target_id="test.minimal.v1",
            target_version="1.0.0",
        )
        pkg = load_skill_package(invoker_dir)
        with pytest.raises(ExecutionError, match="registry"):
            run_skill_package(pkg, {"text": "x"})


# ── recursion protection ─────────────────────────────────────────────


class TestRecursionProtection:
    def test_self_recursion_detected(
        self, reg: LocalRegistry, tmp_path: Path
    ) -> None:
        """Skill that invokes itself."""
        skill = {
            "id": "test.recurse.v1",
            "name": "Self Recurse",
            "version": "1.0.0",
            "description": "Invokes itself.",
            "inputs": [{"name": "text", "type": "string", "required": True}],
            "outputs": [{"name": "result", "type": "string"}],
            "effects": ["pure"],
        }
        graph = {
            "version": 1,
            "nodes": [
                {
                    "id": "call",
                    "op": "skill.invoke",
                    "config": {
                        "skill_id": "test.recurse.v1",
                        "version": "1.0.0",
                    },
                },
            ],
            "edges": [{"from": "input.text", "to": "call.text"}],
            "outputs": {"result": "call.result"},
        }
        pkg_dir = tmp_path / "recurse"
        write_package(
            pkg_dir, skill=skill, graph=graph, examples=minimal_examples(),
        )
        reg.publish(pkg_dir)

        pkg = reg.fetch("test.recurse.v1", "1.0.0")
        validate_skill_package(pkg)
        with pytest.raises(ExecutionError, match="Self-recursion"):
            run_skill_package(pkg, {"text": "x"}, registry=reg)

    def test_mutual_recursion_detected(
        self, reg: LocalRegistry, tmp_path: Path
    ) -> None:
        """A calls B, B calls A."""
        # Skill A
        skill_a = {
            "id": "test.a.v1",
            "name": "A",
            "version": "1.0.0",
            "description": "Calls B.",
            "inputs": [{"name": "text", "type": "string", "required": True}],
            "outputs": [{"name": "result", "type": "string"}],
            "effects": ["pure"],
        }
        graph_a = {
            "version": 1,
            "nodes": [
                {
                    "id": "call",
                    "op": "skill.invoke",
                    "config": {"skill_id": "test.b.v1", "version": "1.0.0"},
                },
            ],
            "edges": [{"from": "input.text", "to": "call.text"}],
            "outputs": {"result": "call.result"},
        }
        write_package(
            tmp_path / "a",
            skill=skill_a, graph=graph_a, examples=minimal_examples(),
        )
        reg.publish(tmp_path / "a")

        # Skill B
        skill_b = {
            "id": "test.b.v1",
            "name": "B",
            "version": "1.0.0",
            "description": "Calls A.",
            "inputs": [{"name": "text", "type": "string", "required": True}],
            "outputs": [{"name": "result", "type": "string"}],
            "effects": ["pure"],
        }
        graph_b = {
            "version": 1,
            "nodes": [
                {
                    "id": "call",
                    "op": "skill.invoke",
                    "config": {"skill_id": "test.a.v1", "version": "1.0.0"},
                },
            ],
            "edges": [{"from": "input.text", "to": "call.text"}],
            "outputs": {"result": "call.result"},
        }
        write_package(
            tmp_path / "b",
            skill=skill_b, graph=graph_b, examples=minimal_examples(),
        )
        reg.publish(tmp_path / "b")

        pkg = reg.fetch("test.a.v1", "1.0.0")
        with pytest.raises(ExecutionError, match="Self-recursion"):
            run_skill_package(pkg, {"text": "x"}, registry=reg)

    def test_depth_two_invoke_succeeds(
        self, reg: LocalRegistry, tmp_path: Path
    ) -> None:
        """A invokes B, B is a simple template. Should succeed."""
        # Target (B)
        target_dir = tmp_path / "target"
        write_package(
            target_dir,
            skill=minimal_skill(),
            graph=minimal_graph(),
            examples=minimal_examples(),
        )
        reg.publish(target_dir)

        # Middle (A) invokes B
        invoker_dir = _make_invoker_package(
            tmp_path / "middle",
            target_id="test.minimal.v1",
            target_version="1.0.0",
        )
        reg.publish(invoker_dir)

        # Top level invokes A
        top_skill = {
            "id": "test.top.v1",
            "name": "Top",
            "version": "1.0.0",
            "description": "Invokes invoker.",
            "inputs": [{"name": "text", "type": "string", "required": True}],
            "outputs": [{"name": "result", "type": "string"}],
            "effects": ["pure"],
        }
        top_graph = {
            "version": 1,
            "nodes": [
                {
                    "id": "call",
                    "op": "skill.invoke",
                    "config": {
                        "skill_id": "test.invoker.v1",
                        "version": "1.0.0",
                    },
                },
            ],
            "edges": [{"from": "input.text", "to": "call.text"}],
            "outputs": {"result": "call.result"},
        }
        top_dir = tmp_path / "top"
        write_package(
            top_dir,
            skill=top_skill, graph=top_graph, examples=minimal_examples(),
        )
        pkg = load_skill_package(top_dir)
        validate_skill_package(pkg)

        result = run_skill_package(pkg, {"text": "deep"}, registry=reg)
        assert result.outputs == {"result": "deep"}
        # Top trace → call node → child trace → call node → child trace
        top_call = result.trace.nodes[0]
        assert top_call.child_trace is not None
        inner_call = top_call.child_trace.nodes[0]
        assert inner_call.child_trace is not None
        assert inner_call.child_trace.skill_id == "test.minimal.v1"
