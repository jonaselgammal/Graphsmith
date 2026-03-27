"""Tests for the runtime executor and planner."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from graphsmith.exceptions import ExecutionError
from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.parser import load_skill_package
from graphsmith.planner.compiler import compile_ir
from graphsmith.planner.ir import IRBlock, IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.runtime import run_skill_package, topological_order
from graphsmith.registry import LocalRegistry
from graphsmith.validator import validate_skill_package

from conftest import EXAMPLE_DIR, minimal_examples, minimal_graph, minimal_skill, write_package


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

    def test_binding_resolution_failure_records_error_trace(self, tmp_path: Path) -> None:
        skill = {
            "id": "test.binding_resolution_error.v1",
            "name": "Binding Resolution Error",
            "version": "1.0.0",
            "description": "Fail during address resolution.",
            "inputs": [{"name": "text", "type": "string", "required": True}],
            "outputs": [{"name": "result", "type": "string"}],
            "effects": ["pure"],
        }
        graph = {
            "version": 1,
            "nodes": [
                {"id": "label", "op": "template.render", "config": {"template": "ok"}},
                {"id": "broken", "op": "text.equals"},
            ],
            "edges": [
                {"from": "input.text", "to": "broken.text"},
                {"from": "label.missing", "to": "broken.other"},
            ],
            "outputs": {"result": "broken.result"},
        }
        write_package(tmp_path / "pkg", skill=skill, graph=graph, examples=minimal_examples())
        pkg = _load_and_validate(tmp_path / "pkg")
        with pytest.raises(ExecutionError, match="label.missing") as exc_info:
            run_skill_package(pkg, {"text": "ok"})

        trace = exc_info.value.trace
        assert trace is not None
        assert trace.nodes[-1].node_id == "broken"
        assert trace.nodes[-1].status == "error"
        assert "label.missing" in (trace.nodes[-1].error or "")

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

    def test_fs_ops_read_and_write_text(self, tmp_path: Path) -> None:
        skill = {
            "id": "test.fs_roundtrip.v1",
            "name": "FS Roundtrip",
            "version": "1.0.0",
            "description": "Write then read text.",
            "inputs": [
                {"name": "path", "type": "string", "required": True},
                {"name": "text", "type": "string", "required": True},
            ],
            "outputs": [{"name": "result", "type": "string"}],
            "effects": ["filesystem_read", "filesystem_write"],
        }
        graph = {
            "version": 1,
            "nodes": [
                {"id": "write", "op": "fs.write_text", "config": {"allow_roots": [str(tmp_path)]}},
                {"id": "read", "op": "fs.read_text", "config": {"allow_roots": [str(tmp_path)]}},
            ],
            "edges": [
                {"from": "input.path", "to": "write.path"},
                {"from": "input.text", "to": "write.text"},
                {"from": "write.path", "to": "read.path"},
            ],
            "outputs": {"result": "read.text"},
        }
        write_package(tmp_path / "pkg", skill=skill, graph=graph, examples=minimal_examples())
        pkg = _load_and_validate(tmp_path / "pkg")
        target = tmp_path / "note.txt"
        result = run_skill_package(pkg, {"path": str(target), "text": "hello env"})
        assert result.outputs == {"result": "hello env"}
        assert target.read_text(encoding="utf-8") == "hello env"

    def test_shell_exec_runs_bounded_command(self, tmp_path: Path) -> None:
        skill = {
            "id": "test.shell_exec.v1",
            "name": "Shell Exec",
            "version": "1.0.0",
            "description": "Run a simple process.",
            "inputs": [],
            "outputs": [{"name": "stdout", "type": "string"}],
            "effects": ["shell_exec"],
        }
        graph = {
            "version": 1,
            "nodes": [
                {
                    "id": "run",
                    "op": "shell.exec",
                    "config": {
                        "argv": ["/bin/echo", "graphsmith"],
                        "cwd": str(tmp_path),
                        "allow_roots": [str(tmp_path)],
                        "check": True,
                    },
                },
            ],
            "edges": [],
            "outputs": {"stdout": "run.stdout"},
        }
        write_package(tmp_path / "pkg", skill=skill, graph=graph, examples=minimal_examples())
        pkg = _load_and_validate(tmp_path / "pkg")
        result = run_skill_package(pkg, {})
        assert result.outputs["stdout"].strip() == "graphsmith"

    def test_fs_read_blocks_paths_outside_allowed_roots(self, tmp_path: Path) -> None:
        skill = {
            "id": "test.fs_guard.v1",
            "name": "FS Guard",
            "version": "1.0.0",
            "description": "Guarded file read.",
            "inputs": [{"name": "path", "type": "string", "required": True}],
            "outputs": [{"name": "text", "type": "string"}],
            "effects": ["filesystem_read"],
        }
        graph = {
            "version": 1,
            "nodes": [
                {"id": "read", "op": "fs.read_text", "config": {"allow_roots": [str(tmp_path)]}},
            ],
            "edges": [{"from": "input.path", "to": "read.path"}],
            "outputs": {"text": "read.text"},
        }
        write_package(tmp_path / "pkg", skill=skill, graph=graph, examples=minimal_examples())
        pkg = _load_and_validate(tmp_path / "pkg")
        outside = tmp_path.parent / "outside.txt"
        outside.write_text("blocked", encoding="utf-8")
        with pytest.raises(ExecutionError, match="outside allowed roots"):
            run_skill_package(pkg, {"path": str(outside)})


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


class TestConditionalExecution:
    def test_when_false_skips_effectful_node(self, tmp_path: Path) -> None:
        skill = {
            "id": "test.conditional.v1",
            "name": "Conditional",
            "version": "1.0.0",
            "description": "Conditional execution.",
            "inputs": [
                {"name": "condition", "type": "boolean", "required": True},
                {"name": "text", "type": "string", "required": True},
            ],
            "outputs": [{"name": "result", "type": "string"}],
            "effects": ["pure"],
        }
        graph = {
            "version": 1,
            "nodes": [
                {"id": "then_step", "op": "template.render", "config": {"template": "then:{{text}}"}, "when": "input.condition"},
                {"id": "else_step", "op": "template.render", "config": {"template": "else:{{text}}"}, "when": "!input.condition"},
                {"id": "choose", "op": "fallback.try"},
            ],
            "edges": [
                {"from": "input.text", "to": "then_step.text"},
                {"from": "input.text", "to": "else_step.text"},
                {"from": "then_step.rendered", "to": "choose.primary"},
                {"from": "else_step.rendered", "to": "choose.fallback"},
            ],
            "outputs": {"result": "choose.result"},
        }
        write_package(tmp_path / "pkg", skill=skill, graph=graph, examples=minimal_examples())
        pkg = _load_and_validate(tmp_path / "pkg")

        result = run_skill_package(pkg, {"condition": False, "text": "x"})
        assert result.outputs == {"result": "else:x"}
        statuses = {node.node_id: node.status for node in result.trace.nodes}
        assert statuses["then_step"] == "skipped"
        assert statuses["else_step"] == "ok"
        assert statuses["choose"] == "ok"

    def test_when_true_runs_node(self, tmp_path: Path) -> None:
        skill = {
            "id": "test.when_true.v1",
            "name": "WhenTrue",
            "version": "1.0.0",
            "description": "When guard runs node.",
            "inputs": [
                {"name": "enabled", "type": "boolean", "required": True},
                {"name": "text", "type": "string", "required": True},
            ],
            "outputs": [{"name": "result", "type": "string"}],
            "effects": ["pure"],
        }
        graph = {
            "version": 1,
            "nodes": [
                {"id": "step", "op": "template.render", "config": {"template": "{{text}}"}, "when": "input.enabled"},
            ],
            "edges": [
                {"from": "input.text", "to": "step.text"},
            ],
            "outputs": {"result": "step.rendered"},
        }
        write_package(tmp_path / "pkg", skill=skill, graph=graph, examples=minimal_examples())
        pkg = _load_and_validate(tmp_path / "pkg")

        result = run_skill_package(pkg, {"enabled": True, "text": "hello"})
        assert result.outputs == {"result": "hello"}
        assert result.trace.nodes[0].status == "ok"

    def test_when_dependency_affects_topological_order(self, tmp_path: Path) -> None:
        skill = {
            "id": "test.when_order.v1",
            "name": "WhenOrder",
            "version": "1.0.0",
            "description": "When dependency participates in order.",
            "inputs": [{"name": "text", "type": "string", "required": True}],
            "outputs": [{"name": "result", "type": "string"}],
            "effects": ["pure"],
        }
        graph = {
            "version": 1,
            "nodes": [
                {"id": "gate", "op": "template.render", "config": {"template": "{{text}}"}},
                {"id": "step", "op": "template.render", "config": {"template": "[{{text}}]"}, "when": "gate.rendered"},
            ],
            "edges": [
                {"from": "input.text", "to": "gate.text"},
                {"from": "input.text", "to": "step.text"},
            ],
            "outputs": {"result": "step.rendered"},
        }
        write_package(tmp_path / "pkg", skill=skill, graph=graph, examples=minimal_examples())
        pkg = _load_and_validate(tmp_path / "pkg")
        assert topological_order(pkg) == ["gate", "step"]


class TestBoundedIteration:
    def test_parallel_map_skill_invoke_in_runtime(self, tmp_path: Path) -> None:
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "text.normalize.v1")

        skill = {
            "id": "test.iterate.v1",
            "name": "Iterate",
            "version": "1.0.0",
            "description": "Map normalize over an array.",
            "inputs": [{"name": "items", "type": "array<string>", "required": True}],
            "outputs": [{"name": "result", "type": "object"}],
            "effects": ["pure"],
        }
        graph = {
            "version": 1,
            "nodes": [
                {
                    "id": "map",
                    "op": "parallel.map",
                    "config": {
                        "op": "skill.invoke",
                        "item_input": "text",
                        "op_config": {"skill_id": "text.normalize.v1", "version": "1.0.0"},
                        "max_items": 10,
                    },
                },
            ],
            "edges": [
                {"from": "input.items", "to": "map.items"},
            ],
            "outputs": {"result": "map.results"},
        }
        write_package(tmp_path / "pkg", skill=skill, graph=graph, examples={"examples": []})
        pkg = _load_and_validate(tmp_path / "pkg")

        result = run_skill_package(pkg, {"items": ["  Alice ", "Bob  "]}, registry=reg)
        assert result.outputs == {
            "result": [
                {"normalized": "alice"},
                {"normalized": "bob"},
            ]
        }

    def test_parallel_map_limit_failure_in_runtime(self, tmp_path: Path) -> None:
        skill = {
            "id": "test.iterate.limit.v1",
            "name": "IterateLimit",
            "version": "1.0.0",
            "description": "Map with hard limit.",
            "inputs": [{"name": "items", "type": "array<string>", "required": True}],
            "outputs": [{"name": "result", "type": "object"}],
            "effects": ["pure"],
        }
        graph = {
            "version": 1,
            "nodes": [
                {
                    "id": "map",
                    "op": "parallel.map",
                    "config": {
                        "op": "template.render",
                        "op_config": {"template": "{{item}}"},
                        "max_items": 1,
                    },
                },
            ],
            "edges": [
                {"from": "input.items", "to": "map.items"},
            ],
            "outputs": {"result": "map.results"},
        }
        write_package(tmp_path / "pkg", skill=skill, graph=graph, examples={"examples": []})
        pkg = _load_and_validate(tmp_path / "pkg")

        with pytest.raises(ExecutionError, match="exceeds configured limit 1"):
            run_skill_package(pkg, {"items": ["a", "b"]})

    def test_loop_block_executes_and_collects_named_outputs(self, tmp_path: Path) -> None:
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "text.normalize.v1")

        ir = PlanningIR(
            goal="normalize items",
            inputs=[IRInput(name="items", type="array<string>")],
            steps=[],
            blocks=[
                IRBlock(
                    name="normalize_each",
                    kind="loop",
                    collection=IRSource(step="input", port="items"),
                    inputs={"text": IRSource(binding="item")},
                    steps=[
                        IRStep(
                            name="normalize",
                            skill_id="text.normalize.v1",
                            sources={"text": IRSource(step="input", port="text")},
                        )
                    ],
                    final_outputs={"normalized": IROutputRef(step="normalize", port="normalized")},
                    max_items=10,
                )
            ],
            final_outputs={"normalized": IROutputRef(step="normalize_each", port="normalized")},
            effects=["pure"],
        )
        glue = compile_ir(ir)
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

        result = run_skill_package(pkg, {"items": ["  Alice ", "Bob  "]}, registry=reg)
        assert result.outputs == {"normalized": ["alice", "bob"]}
        assert result.trace.nodes[0].op == "parallel.map"
        assert result.trace.nodes[0].child_trace is not None
        child = result.trace.nodes[0].child_trace
        assert child is not None
        assert len(child.nodes) == 2
        assert child.nodes[0].node_id == "item_0"

    def test_loop_block_can_use_outer_passthrough_inputs(self) -> None:
        ir = PlanningIR(
            goal="format items with prefix",
            inputs=[IRInput(name="items", type="array<string>"), IRInput(name="prefix", type="string")],
            steps=[],
            blocks=[
                IRBlock(
                    name="format_each",
                    kind="loop",
                    collection=IRSource(step="input", port="items"),
                    inputs={
                        "value": IRSource(binding="item"),
                        "prefix": IRSource(step="input", port="prefix"),
                    },
                    steps=[
                        IRStep(
                            name="render",
                            skill_id="template.render",
                            sources={
                                "value": IRSource(step="input", port="value"),
                                "prefix": IRSource(step="input", port="prefix"),
                            },
                            config={"template": "{{prefix}}:{{value}}"},
                        )
                    ],
                    final_outputs={"rendered": IROutputRef(step="render", port="rendered")},
                    max_items=10,
                )
            ],
            final_outputs={"rendered": IROutputRef(step="format_each", port="rendered")},
            effects=["pure"],
        )
        glue = compile_ir(ir)
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

        result = run_skill_package(pkg, {"items": ["a", "b"], "prefix": "item"})
        assert result.outputs == {"rendered": ["item:a", "item:b"]}


class TestBranchBlocks:
    def test_branch_block_executes_then_path(self) -> None:
        ir = PlanningIR(
            goal="branch format",
            inputs=[IRInput(name="text"), IRInput(name="enabled", type="boolean")],
            steps=[],
            blocks=[
                IRBlock(
                    name="format_branch",
                    kind="branch",
                    condition=IRSource(step="input", port="enabled"),
                    inputs={"text": IRSource(step="input", port="text")},
                    then_steps=[
                        IRStep(
                            name="then_render",
                            skill_id="template.render",
                            sources={"text": IRSource(step="input", port="text")},
                            config={"template": "then:{{text}}"},
                        )
                    ],
                    else_steps=[
                        IRStep(
                            name="else_render",
                            skill_id="template.render",
                            sources={"text": IRSource(step="input", port="text")},
                            config={"template": "else:{{text}}"},
                        )
                    ],
                    then_outputs={"rendered": IROutputRef(step="then_render", port="rendered")},
                    else_outputs={"rendered": IROutputRef(step="else_render", port="rendered")},
                )
            ],
            final_outputs={"rendered": IROutputRef(step="format_branch", port="rendered")},
            effects=["pure"],
        )
        glue = compile_ir(ir)
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

        result = run_skill_package(pkg, {"text": "x", "enabled": True})
        assert result.outputs == {"rendered": "then:x"}
        statuses = {node.node_id: node.status for node in result.trace.nodes}
        assert statuses["format_branch_then_then_render"] == "ok"
        assert statuses["format_branch_else_else_render"] == "skipped"

    def test_branch_block_executes_else_path(self) -> None:
        ir = PlanningIR(
            goal="branch format",
            inputs=[IRInput(name="text"), IRInput(name="enabled", type="boolean")],
            steps=[],
            blocks=[
                IRBlock(
                    name="format_branch",
                    kind="branch",
                    condition=IRSource(step="input", port="enabled"),
                    inputs={"text": IRSource(step="input", port="text")},
                    then_steps=[
                        IRStep(
                            name="then_render",
                            skill_id="template.render",
                            sources={"text": IRSource(step="input", port="text")},
                            config={"template": "then:{{text}}"},
                        )
                    ],
                    else_steps=[
                        IRStep(
                            name="else_render",
                            skill_id="template.render",
                            sources={"text": IRSource(step="input", port="text")},
                            config={"template": "else:{{text}}"},
                        )
                    ],
                    then_outputs={"rendered": IROutputRef(step="then_render", port="rendered")},
                    else_outputs={"rendered": IROutputRef(step="else_render", port="rendered")},
                )
            ],
            final_outputs={"rendered": IROutputRef(step="format_branch", port="rendered")},
            effects=["pure"],
        )
        glue = compile_ir(ir)
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

        result = run_skill_package(pkg, {"text": "x", "enabled": False})
        assert result.outputs == {"rendered": "else:x"}
        statuses = {node.node_id: node.status for node in result.trace.nodes}
        assert statuses["format_branch_then_then_render"] == "skipped"
        assert statuses["format_branch_else_else_render"] == "ok"
