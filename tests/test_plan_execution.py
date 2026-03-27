"""Tests for plan execution: plan-and-run, save/load plans, run-plan."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from graphsmith.cli.main import app
from graphsmith.exceptions import ExecutionError, PlannerError
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphNode
from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.planner import (
    GlueGraph,
    MockPlannerBackend,
    PlanResult,
    compose_plan,
    load_plan,
    run_glue_graph,
    save_plan,
)
from graphsmith.planner.compiler import compile_ir
from graphsmith.planner.ir import IRBlock, IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.planner.graph_repair import (
    normalize_glue_graph_contracts,
    repair_glue_graph_from_runtime_error,
)
from graphsmith.registry import LocalRegistry

from conftest import EXAMPLE_DIR, minimal_examples, minimal_graph, minimal_skill, write_package

runner = CliRunner()


@pytest.fixture()
def reg(tmp_path: Path) -> LocalRegistry:
    r = LocalRegistry(root=tmp_path / "registry")
    r.publish(EXAMPLE_DIR / "text.summarize.v1")
    return r


@pytest.fixture()
def minimal_reg(tmp_path: Path) -> LocalRegistry:
    r = LocalRegistry(root=tmp_path / "registry")
    pkg_dir = tmp_path / "pkg"
    write_package(pkg_dir, skill=minimal_skill(), graph=minimal_graph(), examples=minimal_examples())
    r.publish(pkg_dir)
    return r


# ── run_glue_graph ───────────────────────────────────────────────────


class TestRunGlueGraph:
    def test_run_valid_plan(self, reg: LocalRegistry) -> None:
        result = compose_plan("summarize text", reg, MockPlannerBackend())
        assert result.status == "success" and result.graph is not None

        exec_result = run_glue_graph(
            result.graph,
            {"text": "Cats sleep", "max_sentences": 1},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=reg,
        )
        assert exec_result.trace.status == "ok"
        assert len(exec_result.outputs) > 0

    def test_run_minimal_plan(self, minimal_reg: LocalRegistry) -> None:
        result = compose_plan("test", minimal_reg, MockPlannerBackend())
        assert result.status == "success" and result.graph is not None

        exec_result = run_glue_graph(result.graph, {"text": "hello"}, registry=minimal_reg)
        assert exec_result.outputs == {"result": "hello"}

    def test_trace_has_glue_id(self, minimal_reg: LocalRegistry) -> None:
        result = compose_plan("test", minimal_reg, MockPlannerBackend())
        exec_result = run_glue_graph(result.graph, {"text": "x"}, registry=minimal_reg)
        assert exec_result.trace.skill_id.startswith("_glue.")

    def test_invalid_glue_raises(self) -> None:
        from graphsmith.models.common import IOField
        from graphsmith.models.graph import GraphBody, GraphNode

        bad_glue = GlueGraph(
            goal="bad",
            inputs=[IOField(name="x", type="string")],
            outputs=[IOField(name="y", type="string")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[GraphNode(id="n", op="magic.spell")],
                edges=[],
                outputs={"y": "n.out"},
            ),
        )
        with pytest.raises(PlannerError, match="validation failed"):
            run_glue_graph(bad_glue, {"x": "hello"})

    def test_partial_plan_not_executed(self, reg: LocalRegistry) -> None:
        """Compose a plan with desired_outputs that can't be met → partial."""
        result = compose_plan(
            "summarize text", reg, MockPlannerBackend(),
            desired_outputs=[IOField(name="nonexistent", type="string")],
        )
        assert result.status == "partial"
        # run_glue_graph only takes a GlueGraph, not a PlanResult.
        # Callers must check status before calling.

    def test_runtime_repairs_parallel_map_output_alias(self) -> None:
        glue = GlueGraph(
            goal="map text",
            inputs=[IOField(name="items", type="array<string>")],
            outputs=[IOField(name="result", type="object")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="map",
                        op="parallel.map",
                        config={
                            "op": "template.render",
                            "item_input": "text",
                            "op_config": {"template": "{{text}}"},
                            "max_items": 10,
                        },
                    )
                ],
                edges=[{"from": "input.items", "to": "map.items"}],
                outputs={"result": "map.mapped"},
            ),
        )

        exec_result = run_glue_graph(glue, {"items": ["a", "b"]})
        assert exec_result.outputs == {
            "result": [
                {"rendered": "a"},
                {"rendered": "b"},
            ]
        }
        assert exec_result.repairs == [
            "graph:map: rewrite mapped output references to results"
        ]

    def test_runtime_repairs_array_map_input_alias(self) -> None:
        glue = GlueGraph(
            goal="map field",
            inputs=[IOField(name="items", type="array<object>")],
            outputs=[IOField(name="result", type="object")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="map",
                        op="array.map",
                        config={"field": "name"},
                    )
                ],
                edges=[{"from": "input.items", "to": "map.array"}],
                outputs={"result": "map.mapped"},
            ),
        )

        exec_result = run_glue_graph(
            glue,
            {"items": [{"name": "alice"}, {"name": "bob"}]},
        )
        assert exec_result.outputs == {"result": ["alice", "bob"]}
        assert exec_result.repairs == [
            "graph:map: rewrite array.map input references from array to items"
        ]

    def test_normalizes_legacy_parallel_map_shorthand(self, tmp_path: Path) -> None:
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "text.normalize.v1")

        glue = GlueGraph(
            goal="normalize strings",
            inputs=[IOField(name="strings", type="array<string>")],
            outputs=[IOField(name="normalized", type="array<string>")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="normalize_all",
                        op="parallel.map",
                        config={"operation": "text.normalize"},
                    )
                ],
                edges=[{"from": "input.strings", "to": "normalize_all.array"}],
                outputs={"normalized": "normalize_all.normalized"},
            ),
        )

        exec_result = run_glue_graph(
            glue,
            {"strings": ["  Alice  ", " BOB "]},
            registry=reg,
        )
        assert exec_result.outputs == {"normalized": ["alice", "bob"]}
        assert exec_result.repairs == [
            "graph:normalize_all: rewrite parallel.map input references from array to items",
            "graph:normalize_all: lift parallel.map operation 'text.normalize' into runtime config",
            "graph:normalize_all: enable aggregated named outputs for parallel.map",
        ]

    def test_runtime_repairs_parallel_map_result_alias(self) -> None:
        glue = GlueGraph(
            goal="map text",
            inputs=[IOField(name="items", type="array<string>")],
            outputs=[IOField(name="result", type="object")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="map",
                        op="parallel.map",
                        config={
                            "op": "template.render",
                            "item_input": "text",
                            "op_config": {"template": "{{text}}"},
                            "max_items": 10,
                        },
                    )
                ],
                edges=[{"from": "input.items", "to": "map.items"}],
                outputs={"result": "map.result"},
            ),
        )

        exec_result = run_glue_graph(glue, {"items": ["a", "b"]})
        assert exec_result.outputs == {
            "result": [
                {"rendered": "a"},
                {"rendered": "b"},
            ]
        }
        assert exec_result.repairs == [
            "graph:map: enable aggregated named outputs for parallel.map",
            "runtime:map: rewrite result output references to results",
        ]

    def test_runtime_trace_regenerates_loop_region(self) -> None:
        ir = PlanningIR(
            goal="format each item",
            inputs=[IRInput(name="items", type="array<string>")],
            steps=[],
            blocks=[
                IRBlock(
                    name="format_each",
                    kind="loop",
                    collection=IRSource(step="input", port="items"),
                    inputs={"text": IRSource(binding="item")},
                    steps=[
                        IRStep(
                            name="render",
                            skill_id="template.render",
                            sources={"text": IRSource(step="input", port="text")},
                            config={"template": "{{text}}"},
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
        loop_node = glue.graph.nodes[0]
        broken_config = dict(loop_node.config)
        broken_config["item_inputs"] = ["missing"]
        glue = glue.model_copy(
            update={
                "graph": GraphBody(
                    version=glue.graph.version,
                    nodes=[loop_node.model_copy(update={"config": broken_config})],
                    edges=list(glue.graph.edges),
                    outputs=dict(glue.graph.outputs),
                )
            }
        )

        repaired_block = json.dumps({
            "block": ir.blocks[0].model_dump(mode="json")
        })

        class RepairProvider:
            def __init__(self) -> None:
                self.calls = 0

            def generate(self, prompt: str, **kwargs: Any) -> str:
                self.calls += 1
                return repaired_block

        provider = RepairProvider()
        exec_result = run_glue_graph(
            glue,
            {"items": ["a", "b"]},
            llm_provider=provider,  # type: ignore[arg-type]
        )
        assert exec_result.outputs == {"rendered": ["a", "b"]}
        assert exec_result.repairs == [
            "graph:format_each: enable aggregated named outputs for parallel.map",
            "runtime:format_each: regenerated loop region from runtime trace"
        ]
        assert provider.calls == 1

    def test_runtime_repairs_nested_synthesized_loop_region(self, tmp_path: Path) -> None:
        reg = LocalRegistry(root=tmp_path / "reg")
        ir = PlanningIR(
            goal="format each item",
            inputs=[IRInput(name="items", type="array<string>")],
            steps=[],
            blocks=[
                IRBlock(
                    name="format_each",
                    kind="loop",
                    collection=IRSource(step="input", port="items"),
                    inputs={"text": IRSource(binding="item")},
                    steps=[
                        IRStep(
                            name="render",
                            skill_id="template.render",
                            sources={"text": IRSource(step="input", port="text")},
                            config={"template": "{{text}}"},
                        )
                    ],
                    final_outputs={"rendered": IROutputRef(step="render", port="rendered")},
                    max_items=10,
                )
            ],
            final_outputs={"rendered": IROutputRef(step="format_each", port="rendered")},
            effects=["pure"],
        )
        synth_glue = compile_ir(ir)
        broken_node = synth_glue.graph.nodes[0]
        broken_config = dict(broken_node.config)
        broken_config["item_inputs"] = ["missing"]
        synth_pkg_dir = write_package(
            tmp_path / "synth_pkg",
            skill={
                "id": "synth.format_each.v1",
                "name": "Synth Format Each",
                "version": "1.0.0",
                "description": "format each item",
                "inputs": [{"name": "items", "type": "array<string>", "required": True}],
                "outputs": [{"name": "rendered", "type": "array<string>"}],
                "effects": ["pure"],
                "tags": ["synthesized", "subgraph"],
            },
            graph={
                "version": 1,
                "nodes": [broken_node.model_copy(update={"config": broken_config}).model_dump(mode="json", by_alias=True)],
                "edges": [edge.model_dump(mode="json", by_alias=True) for edge in synth_glue.graph.edges],
                "outputs": dict(synth_glue.graph.outputs),
            },
            examples=minimal_examples(),
        )
        reg.publish(synth_pkg_dir)

        outer_glue = GlueGraph(
            goal="call synthesized loop",
            inputs=[IOField(name="items", type="array<string>")],
            outputs=[IOField(name="rendered", type="array<string>")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="invoke_loop",
                        op="skill.invoke",
                        config={"skill_id": "synth.format_each.v1", "version": "1.0.0"},
                    )
                ],
                edges=[{"from": "input.items", "to": "invoke_loop.items"}],
                outputs={"rendered": "invoke_loop.rendered"},
            ),
        )

        repaired_block = json.dumps({"block": ir.blocks[0].model_dump(mode="json")})

        class RepairProvider:
            def __init__(self) -> None:
                self.calls = 0

            def generate(self, prompt: str, **kwargs: Any) -> str:
                self.calls += 1
                return repaired_block

        provider = RepairProvider()
        exec_result = run_glue_graph(
            outer_glue,
            {"items": ["a", "b"]},
            llm_provider=provider,  # type: ignore[arg-type]
            registry=reg,
        )
        assert exec_result.outputs == {"rendered": ["a", "b"]}
        assert "runtime:format_each: regenerated loop region from runtime trace" in exec_result.repairs
        swap_actions = [
            action for action in exec_result.repairs
            if action.startswith("runtime:invoke_loop: swapped repaired nested skill ")
        ]
        assert len(swap_actions) == 1
        repaired_entries = [entry for entry in reg.list_all() if entry.id.startswith("repair.synth_format_each_v1_")]
        assert len(repaired_entries) == 1
        repaired_pkg = reg.fetch(repaired_entries[0].id, repaired_entries[0].version)
        assert repaired_pkg.graph.nodes[0].config.get("item_inputs") != ["missing"]
        assert provider.calls == 1

    def test_runtime_repairs_branch_region_from_trace(self, tmp_path: Path) -> None:
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "dev.run_pytest.v1")
        reg.publish(EXAMPLE_DIR / "text.prefix_lines.v1")

        project = Path.cwd() / ".tmp_branch_region_project"
        project.mkdir(exist_ok=True)
        (project / "test_ok.py").write_text(
            "def test_ok():\n    assert True\n",
            encoding="utf-8",
        )

        ir = PlanningIR(
            goal="run pytest and prefix output by status",
            inputs=[IRInput(name="cwd", type="string")],
            steps=[
                IRStep(
                    name="pytest",
                    skill_id="dev.run_pytest.v1",
                    sources={"cwd": IRSource(step="input", port="cwd")},
                ),
                IRStep(name="zero", skill_id="template.render", config={"template": "0"}),
                IRStep(
                    name="is_success",
                    skill_id="text.equals",
                    sources={
                        "text": IRSource(step="pytest", port="exit_code"),
                        "other": IRSource(step="zero", port="rendered"),
                    },
                ),
            ],
            blocks=[
                IRBlock(
                    name="format_output",
                    kind="branch",
                    condition=IRSource(step="is_success", port="result"),
                    inputs={"stdout": IRSource(step="pytest", port="stdout")},
                    then_steps=[
                        IRStep(name="pass_label", skill_id="template.render", config={"template": "PASS"}),
                        IRStep(
                            name="prefix_pass",
                            skill_id="text.prefix_lines.v1",
                            sources={
                                "text": IRSource(step="input", port="stdout"),
                                "prefix": IRSource(step="pass_label", port="rendered"),
                            },
                        ),
                    ],
                    else_steps=[
                        IRStep(name="fail_label", skill_id="template.render", config={"template": "FAIL"}),
                        IRStep(
                            name="prefix_fail",
                            skill_id="text.prefix_lines.v1",
                            sources={
                                "text": IRSource(step="input", port="stdout"),
                                "prefix": IRSource(step="fail_label", port="rendered"),
                            },
                        ),
                    ],
                    then_outputs={"prefixed": IROutputRef(step="prefix_pass", port="prefixed")},
                    else_outputs={"prefixed": IROutputRef(step="prefix_fail", port="prefixed")},
                )
            ],
            final_outputs={"prefixed": IROutputRef(step="format_output", port="prefixed")},
            effects=["shell_exec", "pure"],
        )
        glue = compile_ir(ir)

        broken_edges = []
        for edge in glue.graph.edges:
            if edge.to == "format_output_then_prefix_pass.prefix":
                broken_edges.append(edge.model_copy(update={"from_": "zero.missing"}))
            else:
                broken_edges.append(edge)
        glue = glue.model_copy(
            update={
                "graph": glue.graph.model_copy(update={"edges": broken_edges}),
            }
        )

        repaired_block = json.dumps({"block": ir.blocks[0].model_dump(mode="json")})

        class RepairProvider:
            def __init__(self) -> None:
                self.calls = 0

            def generate(self, prompt: str, **kwargs: Any) -> str:
                self.calls += 1
                return repaired_block

        provider = RepairProvider()
        exec_result = run_glue_graph(
            glue,
            {"cwd": str(project)},
            llm_provider=provider,  # type: ignore[arg-type]
            registry=reg,
        )
        assert "PASS" in exec_result.outputs["prefixed"]
        assert "runtime:format_output: regenerated branch region from runtime trace" in exec_result.repairs
        assert provider.calls == 1

    def test_runtime_repairs_nested_multi_region_test_skill(self, tmp_path: Path) -> None:
        project = Path.cwd() / f".tmp_nested_multi_region_project_{tmp_path.name}"
        project.mkdir(exist_ok=True)
        input_file = project / "input.txt"
        output_file = project / "output.txt"
        input_file.write_text("hello\nworld\n", encoding="utf-8")
        (project / "test_ok.py").write_text(
            "def test_ok():\n    assert True\n",
            encoding="utf-8",
        )

        reg = LocalRegistry(root=tmp_path / "reg")
        read_skill_dir = write_package(
            tmp_path / "fs_read_pkg",
            skill={
                "id": "fs.read_text.v1",
                "name": "Read Text File",
                "version": "1.0.0",
                "description": "Read a text file from disk.",
                "inputs": [{"name": "path", "type": "string", "required": True}],
                "outputs": [{"name": "text", "type": "string"}],
                "effects": ["filesystem_read"],
                "tags": ["filesystem", "io"],
            },
            graph={
                "version": 1,
                "nodes": [{
                    "id": "read",
                    "op": "fs.read_text",
                    "config": {"allow_roots": [str(project)]},
                }],
                "edges": [{"from": "input.path", "to": "read.path"}],
                "outputs": {"text": "read.text"},
            },
            examples=minimal_examples(),
        )
        reg.publish(read_skill_dir)
        write_skill_dir = write_package(
            tmp_path / "fs_write_pkg",
            skill={
                "id": "fs.write_text.v1",
                "name": "Write Text File",
                "version": "1.0.0",
                "description": "Write a text file to disk.",
                "inputs": [
                    {"name": "path", "type": "string", "required": True},
                    {"name": "text", "type": "string", "required": True},
                ],
                "outputs": [
                    {"name": "path", "type": "string"},
                    {"name": "written", "type": "boolean"},
                ],
                "effects": ["filesystem_write"],
                "tags": ["filesystem", "io"],
            },
            graph={
                "version": 1,
                "nodes": [{
                    "id": "write",
                    "op": "fs.write_text",
                    "config": {"allow_roots": [str(project)]},
                }],
                "edges": [
                    {"from": "input.path", "to": "write.path"},
                    {"from": "input.text", "to": "write.text"},
                ],
                "outputs": {"path": "write.path", "written": "write.written"},
            },
            examples=minimal_examples(),
        )
        reg.publish(write_skill_dir)
        pytest_skill_dir = write_package(
            tmp_path / "run_pytest_pkg",
            skill={
                "id": "dev.run_pytest.v1",
                "name": "Run Pytest",
                "version": "1.0.0",
                "description": "Run pytest in a project directory.",
                "inputs": [{"name": "cwd", "type": "string", "required": True}],
                "outputs": [
                    {"name": "stdout", "type": "string"},
                    {"name": "stderr", "type": "string"},
                    {"name": "exit_code", "type": "string"},
                ],
                "effects": ["shell_exec"],
                "tags": ["dev", "testing"],
            },
            graph={
                "version": 1,
                "nodes": [{
                    "id": "run",
                    "op": "shell.exec",
                    "config": {
                        "argv": ["pytest", "-q"],
                        "allow_roots": [str(project)],
                        "timeout_ms": 20000,
                    },
                }],
                "edges": [{"from": "input.cwd", "to": "run.cwd"}],
                "outputs": {
                    "stdout": "run.stdout",
                    "stderr": "run.stderr",
                    "exit_code": "run.exit_code",
                },
            },
            examples=minimal_examples(),
        )
        reg.publish(pytest_skill_dir)
        reg.publish(EXAMPLE_DIR / "text.title_case.v1")
        reg.publish(EXAMPLE_DIR / "text.prefix_lines.v1")

        edit_skill_dir = write_package(
            tmp_path / "edit_region_pkg",
            skill={
                "id": "synth.file_region.v1",
                "name": "Synth File Region",
                "version": "1.0.0",
                "description": "read transform write region",
                "inputs": [
                    {"name": "input_path", "type": "string", "required": True},
                    {"name": "output_path", "type": "string", "required": True},
                ],
                "outputs": [{"name": "path", "type": "string"}],
                "effects": ["filesystem_read", "filesystem_write", "pure"],
                "tags": ["synthesized", "subgraph"],
            },
            graph={
                "version": 1,
                "nodes": [
                    {"id": "read", "op": "skill.invoke", "config": {"skill_id": "fs.read_text.v1", "version": "1.0.0"}},
                    {"id": "transform", "op": "skill.invoke", "config": {"skill_id": "text.title_case.v1", "version": "1.0.0"}},
                    {"id": "write", "op": "skill.invoke", "config": {"skill_id": "fs.write_text.v1", "version": "1.0.0"}},
                ],
                "edges": [
                    {"from": "input.input_path", "to": "read.path"},
                    {"from": "read.text", "to": "transform.text"},
                    {"from": "input.output_path", "to": "write.path"},
                    {"from": "transform.titled", "to": "write.text"},
                ],
                "outputs": {"path": "write.path"},
            },
            examples=minimal_examples(),
        )
        reg.publish(edit_skill_dir)

        branch_ir = PlanningIR(
            goal="run pytest and prefix output by status",
            inputs=[
                IRInput(name="cwd", type="string"),
                IRInput(name="after_path", type="string"),
            ],
            steps=[
                IRStep(
                    name="pytest",
                    skill_id="dev.run_pytest.v1",
                    sources={"cwd": IRSource(step="input", port="cwd")},
                ),
                IRStep(name="zero", skill_id="template.render", config={"template": "0"}),
                IRStep(
                    name="is_success",
                    skill_id="text.equals",
                    sources={
                        "text": IRSource(step="pytest", port="exit_code"),
                        "other": IRSource(step="zero", port="rendered"),
                    },
                ),
            ],
            blocks=[
                IRBlock(
                    name="format_output",
                    kind="branch",
                    condition=IRSource(step="is_success", port="result"),
                    inputs={"stdout": IRSource(step="pytest", port="stdout")},
                    then_steps=[
                        IRStep(name="pass_label", skill_id="template.render", config={"template": "PASS"}),
                        IRStep(
                            name="prefix_pass",
                            skill_id="text.prefix_lines.v1",
                            sources={
                                "text": IRSource(step="input", port="stdout"),
                                "prefix": IRSource(step="pass_label", port="rendered"),
                            },
                        ),
                    ],
                    else_steps=[
                        IRStep(name="fail_label", skill_id="template.render", config={"template": "FAIL"}),
                        IRStep(
                            name="prefix_fail",
                            skill_id="text.prefix_lines.v1",
                            sources={
                                "text": IRSource(step="input", port="stdout"),
                                "prefix": IRSource(step="fail_label", port="rendered"),
                            },
                        ),
                    ],
                    then_outputs={"prefixed": IROutputRef(step="prefix_pass", port="prefixed")},
                    else_outputs={"prefixed": IROutputRef(step="prefix_fail", port="prefixed")},
                )
            ],
            final_outputs={"stdout": IROutputRef(step="format_output", port="prefixed")},
            effects=["shell_exec", "pure"],
        )
        test_glue = compile_ir(branch_ir)
        broken_edges = []
        for edge in test_glue.graph.edges:
            if edge.to == "format_output_then_prefix_pass.prefix":
                broken_edges.append(edge.model_copy(update={"from_": "zero.missing"}))
            else:
                broken_edges.append(edge)
        test_skill_dir = write_package(
            tmp_path / "test_region_pkg",
            skill={
                "id": "synth.test_region.v1",
                "name": "Synth Test Region",
                "version": "1.0.0",
                "description": "test region",
                "inputs": [
                    {"name": "cwd", "type": "string", "required": True},
                    {"name": "after_path", "type": "string", "required": True},
                ],
                "outputs": [{"name": "stdout", "type": "string"}],
                "effects": ["shell_exec", "pure"],
                "tags": ["synthesized", "subgraph"],
            },
            graph={
                "version": 1,
                "nodes": [
                    {"id": "after_path_token", "op": "template.render", "config": {"template": "{{after_path}}"}},
                    *[node.model_dump(mode="json", by_alias=True) for node in test_glue.graph.nodes],
                ],
                "edges": [
                    {"from": "input.after_path", "to": "after_path_token.after_path"},
                    *[edge.model_dump(mode="json", by_alias=True) for edge in broken_edges],
                ],
                "outputs": dict(test_glue.graph.outputs),
            },
            examples=minimal_examples(),
        )
        reg.publish(test_skill_dir)

        outer_glue = GlueGraph(
            goal="edit file then run tests",
            inputs=[
                IOField(name="input_path", type="string"),
                IOField(name="output_path", type="string"),
                IOField(name="cwd", type="string"),
            ],
            outputs=[IOField(name="stdout", type="string")],
            effects=["filesystem_read", "filesystem_write", "shell_exec", "pure"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="edit_region",
                        op="skill.invoke",
                        config={"skill_id": "synth.file_region.v1", "version": "1.0.0"},
                    ),
                    GraphNode(
                        id="test_region",
                        op="skill.invoke",
                        config={"skill_id": "synth.test_region.v1", "version": "1.0.0"},
                    ),
                ],
                edges=[
                    {"from": "input.input_path", "to": "edit_region.input_path"},
                    {"from": "input.output_path", "to": "edit_region.output_path"},
                    {"from": "input.cwd", "to": "test_region.cwd"},
                    {"from": "edit_region.path", "to": "test_region.after_path"},
                ],
                outputs={"stdout": "test_region.stdout"},
            ),
        )

        repaired_block = json.dumps({"block": branch_ir.blocks[0].model_dump(mode="json")})

        class RepairProvider:
            def __init__(self) -> None:
                self.calls = 0

            def generate(self, prompt: str, **kwargs: Any) -> str:
                self.calls += 1
                return repaired_block

        provider = RepairProvider()
        exec_result = run_glue_graph(
            outer_glue,
            {
                "input_path": str(input_file),
                "output_path": str(output_file),
                "cwd": str(project),
            },
            llm_provider=provider,  # type: ignore[arg-type]
            registry=reg,
        )

        assert "PASS" in exec_result.outputs["stdout"]
        assert output_file.read_text(encoding="utf-8").startswith("Hello")
        assert "runtime:format_output: regenerated branch region from runtime trace" in exec_result.repairs
        swap_actions = [
            action for action in exec_result.repairs
            if action.startswith("runtime:test_region: swapped repaired nested skill ")
        ]
        assert len(swap_actions) == 1
        repaired_entries = [entry for entry in reg.list_all() if entry.id.startswith("repair.synth_test_region_v1_")]
        assert len(repaired_entries) == 1
        assert provider.calls == 1

    def test_normalizes_nested_parallel_map_skill_target(self, tmp_path: Path) -> None:
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "text.normalize.v1")

        glue = GlueGraph(
            goal="normalize strings",
            inputs=[IOField(name="strings", type="array<string>")],
            outputs=[IOField(name="normalized", type="array<string>")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="normalize_all",
                        op="parallel.map",
                        config={
                            "op": "skill.invoke",
                            "op_config": {
                                "skill_id": {
                                    "skill_id": "text.normalize.v1",
                                    "version": "1.0.0",
                                    "input_mapping": {"text": "item"},
                                    "output_mapping": {"normalized": "result"},
                                },
                                "version": "1.0.0",
                            },
                        },
                    )
                ],
                edges=[{"from": "input.strings", "to": "normalize_all.items"}],
                outputs={"normalized": "normalize_all.normalized"},
            ),
        )

        exec_result = run_glue_graph(
            glue,
            {"strings": ["  Alice  ", " BOB "]},
            registry=reg,
        )
        assert exec_result.outputs == {"normalized": ["alice", "bob"]}
        assert exec_result.repairs == [
            "graph:normalize_all: flatten nested parallel.map skill.invoke target 'text.normalize.v1'",
            "graph:normalize_all: derive parallel.map item_input 'text' from skill mapping",
            "graph:normalize_all: enable aggregated outputs from nested skill output mapping",
        ]

    def test_normalizes_sentiment_prefix_branch_shape(self) -> None:
        glue = GlueGraph(
            goal="Classify the sentiment of this text and if it is positive prefix each line with one label, otherwise prefix each line with a different label",
            inputs=[IOField(name="text", type="string")],
            outputs=[IOField(name="prefixed", type="string")],
            effects=["llm_inference"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(id="classify", op="skill.invoke", config={"skill_id": "text.classify_sentiment.v1"}),
                    GraphNode(id="branch", op="branch.if"),
                    GraphNode(id="prefix_a", op="skill.invoke", config={"skill_id": "text.prefix_lines.v1"}),
                    GraphNode(id="prefix_b", op="skill.invoke", config={"skill_id": "text.prefix_lines.v1"}),
                ],
                edges=[
                    {"from": "input.text", "to": "classify.text"},
                    {"from": "classify.sentiment", "to": "branch.condition"},
                ],
                outputs={"prefixed": "prefix_a.prefixed"},
            ),
        )

        repaired, actions = normalize_glue_graph_contracts(glue)

        assert actions == [
            "graph: canonicalize sentiment prefix branch into guarded branches plus merge"
        ]
        assert {field.name for field in repaired.inputs} == {
            "text",
            "positive_prefix",
            "negative_prefix",
        }
        node_ids = {node.id: node for node in repaired.graph.nodes}
        assert node_ids["merge_prefixed"].op == "fallback.try"
        assert node_ids["prefix_positive"].when == "is_positive.result"
        assert node_ids["prefix_negative"].when == "!is_positive.result"
        assert repaired.graph.outputs["prefixed"] == "merge_prefixed.result"

    def test_aligns_parallel_map_skill_output_from_registry_contract(
        self,
        tmp_path: Path,
    ) -> None:
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "text.normalize.v1")

        glue = GlueGraph(
            goal="normalize strings",
            inputs=[IOField(name="strings", type="array<string>")],
            outputs=[IOField(name="results", type="array<string>")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="normalize_all",
                        op="parallel.map",
                        config={
                            "op": "skill.invoke",
                            "item_input": "text",
                            "op_config": {"skill_id": "text.normalize.v1", "version": "1.0.0"},
                        },
                    )
                ],
                edges=[{"from": "input.strings", "to": "normalize_all.items"}],
                outputs={"results": "normalize_all.results"},
            ),
        )

        repaired, actions = normalize_glue_graph_contracts(glue, registry=reg)
        assert repaired.graph.outputs == {"normalized": "normalize_all.normalized"}
        assert repaired.outputs[0].name == "normalized"
        assert "graph:normalize_all: enable aggregated named outputs for parallel.map" in actions
        assert "graph:normalize_all: align generic output 'results' to named output 'normalized'" in actions

    def test_aligns_generic_parallel_map_output_name(self) -> None:
        glue = GlueGraph(
            goal="normalize strings",
            inputs=[IOField(name="strings", type="array<string>")],
            outputs=[IOField(name="results", type="array<string>")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="normalize_all",
                        op="parallel.map",
                        config={"op": "text.normalize", "item_input": "text"},
                    )
                ],
                edges=[{"from": "input.strings", "to": "normalize_all.items"}],
                outputs={"results": "normalize_all.results"},
            ),
        )

        exec_result = run_glue_graph(glue, {"strings": ["  Alice  ", " BOB "]})
        assert exec_result.outputs == {"normalized": ["alice", "bob"]}
        assert exec_result.repairs == [
            "graph:normalize_all: enable aggregated named outputs for parallel.map",
            "graph:normalize_all: align generic output 'results' to named output 'normalized'",
        ]

    def test_aligns_parallel_map_generic_port_to_named_output(self) -> None:
        glue = GlueGraph(
            goal="normalize strings",
            inputs=[IOField(name="strings", type="array<string>")],
            outputs=[IOField(name="normalized", type="array<string>")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="normalize_all",
                        op="parallel.map",
                        config={"op": "text.normalize", "item_input": "text"},
                    )
                ],
                edges=[{"from": "input.strings", "to": "normalize_all.items"}],
                outputs={"normalized": "normalize_all.results"},
            ),
        )

        exec_result = run_glue_graph(glue, {"strings": ["  Alice  ", " BOB "]})
        assert exec_result.outputs == {"normalized": ["alice", "bob"]}
        assert exec_result.repairs == [
            "graph:normalize_all: enable aggregated named outputs for parallel.map",
            "graph:normalize_all: align generic output 'normalized' to named output 'normalized'",
        ]

    def test_runtime_repair_enables_named_parallel_map_output_from_registry_contract(
        self,
        tmp_path: Path,
    ) -> None:
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "text.normalize.v1")

        glue = GlueGraph(
            goal="normalize strings",
            inputs=[IOField(name="strings", type="array<string>")],
            outputs=[IOField(name="normalized", type="array<string>")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="normalize_all",
                        op="parallel.map",
                        config={
                            "op": "skill.invoke",
                            "item_input": "text",
                            "op_config": {"skill_id": "text.normalize.v1", "version": "1.0.0"},
                        },
                    )
                ],
                edges=[{"from": "input.strings", "to": "normalize_all.items"}],
                outputs={"normalized": "normalize_all.normalized"},
            ),
        )

        repaired, actions = repair_glue_graph_from_runtime_error(
            glue,
            "Address 'normalize_all.normalized' has no value. Available: ['input.strings', 'normalize_all.results']",
            registry=reg,
        )
        node = repaired.graph.nodes[0]
        assert node.config["aggregate_outputs"] is True
        assert actions == [
            "runtime:normalize_all: enable aggregated named output 'normalized' for parallel.map"
        ]


# ── save / load ──────────────────────────────────────────────────────


class TestSaveLoad:
    def test_save_and_load(self, reg: LocalRegistry, tmp_path: Path) -> None:
        result = compose_plan("summarize text", reg, MockPlannerBackend())
        assert result.graph is not None

        plan_path = tmp_path / "plan.json"
        save_plan(result.graph, plan_path)

        loaded = load_plan(plan_path)
        assert loaded.goal == result.graph.goal
        assert len(loaded.inputs) == len(result.graph.inputs)
        assert len(loaded.graph.nodes) == len(result.graph.graph.nodes)

    def test_saved_plan_is_valid_json(self, reg: LocalRegistry, tmp_path: Path) -> None:
        result = compose_plan("summarize text", reg, MockPlannerBackend())
        plan_path = tmp_path / "plan.json"
        save_plan(result.graph, plan_path)

        data = json.loads(plan_path.read_text())
        assert "goal" in data
        assert "inputs" in data
        assert "outputs" in data
        assert "graph" in data
        # It should NOT have skill_id, version, etc. (not a SkillPackage)
        assert "id" not in data
        assert "version" not in data

    def test_load_and_run(self, reg: LocalRegistry, tmp_path: Path) -> None:
        result = compose_plan("summarize text", reg, MockPlannerBackend())
        plan_path = tmp_path / "plan.json"
        save_plan(result.graph, plan_path)

        loaded = load_plan(plan_path)
        exec_result = run_glue_graph(
            loaded,
            {"text": "hello", "max_sentences": 1},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=reg,
        )
        assert exec_result.trace.status == "ok"

    def test_load_nonexistent(self) -> None:
        with pytest.raises(PlannerError, match="not found"):
            load_plan("/nonexistent/plan.json")

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        with pytest.raises(PlannerError, match="Failed to load"):
            load_plan(bad)


# ── CLI: plan --save ─────────────────────────────────────────────────


class TestCLIPlanSave:
    def test_plan_save(self, tmp_path: Path) -> None:
        reg_root = tmp_path / "reg"
        runner.invoke(app, [
            "publish", str(EXAMPLE_DIR / "text.summarize.v1"),
            "--registry", str(reg_root),
        ])
        plan_path = tmp_path / "my_plan.json"
        result = runner.invoke(app, [
            "plan", "summarize text",
            "--registry", str(reg_root),
            "--save", str(plan_path),
        ])
        assert result.exit_code == 0
        assert plan_path.exists()
        data = json.loads(plan_path.read_text())
        assert data["goal"] == "summarize text"


# ── CLI: plan-and-run ────────────────────────────────────────────────


class TestCLIPlanAndRun:
    def test_success(self, tmp_path: Path) -> None:
        reg_root = tmp_path / "reg"
        pkg_dir = tmp_path / "pkg"
        write_package(pkg_dir, skill=minimal_skill(), graph=minimal_graph(), examples=minimal_examples())
        runner.invoke(app, ["publish", str(pkg_dir), "--registry", str(reg_root)])

        result = runner.invoke(app, [
            "plan-and-run", "test",
            "--registry", str(reg_root),
            "--input", '{"text":"hello"}',
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == {"result": "hello"}

    def test_json_output(self, tmp_path: Path) -> None:
        reg_root = tmp_path / "reg"
        pkg_dir = tmp_path / "pkg"
        write_package(pkg_dir, skill=minimal_skill(), graph=minimal_graph(), examples=minimal_examples())
        runner.invoke(app, ["publish", str(pkg_dir), "--registry", str(reg_root)])

        result = runner.invoke(app, [
            "plan-and-run", "test",
            "--registry", str(reg_root),
            "--input", '{"text":"hi"}',
            "--output-format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "plan" in data
        assert "outputs" in data
        assert data["plan"]["status"] == "success"

    def test_empty_registry_fails(self, tmp_path: Path) -> None:
        result = runner.invoke(app, [
            "plan-and-run", "test",
            "--registry", str(tmp_path / "empty_reg"),
        ])
        assert result.exit_code == 1

    def test_trace_persisted(self, tmp_path: Path) -> None:
        reg_root = tmp_path / "reg"
        trace_root = tmp_path / "traces"
        pkg_dir = tmp_path / "pkg"
        write_package(pkg_dir, skill=minimal_skill(), graph=minimal_graph(), examples=minimal_examples())
        runner.invoke(app, ["publish", str(pkg_dir), "--registry", str(reg_root)])

        runner.invoke(app, [
            "plan-and-run", "test",
            "--registry", str(reg_root),
            "--input", '{"text":"hi"}',
            "--trace-root", str(trace_root),
        ])
        traces = list(trace_root.glob("*.json"))
        assert len(traces) == 1

    def test_json_output_includes_runtime_repairs(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        broken_glue = GlueGraph(
            goal="broken but repairable",
            inputs=[IOField(name="items", type="array<string>")],
            outputs=[IOField(name="result", type="object")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="map",
                        op="parallel.map",
                        config={
                            "op": "template.render",
                            "item_input": "text",
                            "op_config": {"template": "{{text}}"},
                            "max_items": 10,
                        },
                    )
                ],
                edges=[{"from": "input.items", "to": "map.items"}],
                outputs={"result": "map.mapped"},
            ),
        )

        def _fake_compose_plan(*args: object, **kwargs: object) -> PlanResult:
            return PlanResult(status="success", graph=broken_glue)

        monkeypatch.setattr("graphsmith.planner.compose_plan", _fake_compose_plan)

        result = runner.invoke(app, [
            "plan-and-run", "repairable",
            "--registry", str(Path.cwd()),
            "--input", '{"items":["a","b"]}',
            "--output-format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["outputs"] == {
            "result": [
                {"rendered": "a"},
                {"rendered": "b"},
            ]
        }
        assert data["runtime_repairs"] == [
            "graph:map: rewrite mapped output references to results"
        ]

    def test_live_provider_is_used_for_execution(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        reg_root = tmp_path / "reg"
        runner.invoke(app, [
            "publish", str(EXAMPLE_DIR / "text.summarize.v1"),
            "--registry", str(reg_root),
        ])

        llm_glue = GlueGraph(
            goal="summarize",
            inputs=[
                IOField(name="text", type="string"),
                IOField(name="max_sentences", type="integer"),
            ],
            outputs=[IOField(name="summary", type="string")],
            effects=["llm_inference"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="summarize",
                        op="skill.invoke",
                        config={"skill_id": "text.summarize.v1", "version": "1.0.0"},
                    )
                ],
                edges=[
                    {"from": "input.text", "to": "summarize.text"},
                    {"from": "input.max_sentences", "to": "summarize.max_sentences"},
                ],
                outputs={"summary": "summarize.summary"},
            ),
        )

        def _fake_compose_plan(*args: object, **kwargs: object) -> PlanResult:
            return PlanResult(status="success", graph=llm_glue)

        monkeypatch.setattr("graphsmith.planner.compose_plan", _fake_compose_plan)
        monkeypatch.setattr(
            "graphsmith.ops.providers.create_provider",
            lambda *args, **kwargs: EchoLLMProvider(prefix=""),
        )

        result = runner.invoke(app, [
            "plan-and-run", "summarize",
            "--registry", str(reg_root),
            "--provider", "anthropic",
            "--input", '{"text":"Cats sleep a lot","max_sentences":1}',
            "--output-format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "Cats sleep a lot" in data["outputs"]["summary"]


# ── CLI: run-plan ────────────────────────────────────────────────────


class TestCLIRunPlan:
    def test_run_saved_plan(self, tmp_path: Path) -> None:
        reg_root = tmp_path / "reg"
        pkg_dir = tmp_path / "pkg"
        write_package(pkg_dir, skill=minimal_skill(), graph=minimal_graph(), examples=minimal_examples())
        runner.invoke(app, ["publish", str(pkg_dir), "--registry", str(reg_root)])

        # Save plan
        plan_path = tmp_path / "plan.json"
        runner.invoke(app, [
            "plan", "test",
            "--registry", str(reg_root),
            "--save", str(plan_path),
        ])
        assert plan_path.exists()

        # Run saved plan
        result = runner.invoke(app, [
            "run-plan", str(plan_path),
            "--input", '{"text":"world"}',
            "--registry", str(reg_root),
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == {"result": "world"}

    def test_run_nonexistent_plan(self, tmp_path: Path) -> None:
        result = runner.invoke(app, [
            "run-plan", str(tmp_path / "nope.json"),
            "--input", '{"text":"x"}',
        ])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "FAIL" in result.output

    def test_run_invalid_plan(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        result = runner.invoke(app, [
            "run-plan", str(bad),
            "--input", '{"text":"x"}',
        ])
        assert result.exit_code == 1
