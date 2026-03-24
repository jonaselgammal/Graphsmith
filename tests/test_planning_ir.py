"""Tests for Planning IR models, compiler, parser, prompt, and backend."""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.compiler import (
    CompilerError,
    CycleError,
    DuplicateStepError,
    DuplicateBindingError,
    EmptyStepsError,
    InvalidEffectError,
    SelfLoopError,
    UnsupportedControlFlowError,
    UnknownBindingError,
    UnknownInputError,
    UnknownOutputStepError,
    UnknownSourceStepError,
    compile_ir,
)
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.planner.ir import IRBinding, IRBlock, IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.ir_parser import IRParseError, parse_ir_output
from graphsmith.planner.ir_prompt import build_ir_planning_context, get_ir_system_message
from graphsmith.planner.models import PlanRequest
from graphsmith.validator import validate_skill_package


# ── IR model tests ──────────────────────────────────────────────────


class TestIRModels:
    def test_minimal_ir(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(
                    name="call",
                    skill_id="text.summarize.v1",
                    sources={"text": IRSource(step="input", port="text")},
                )
            ],
            final_outputs={"summary": IROutputRef(step="call", port="summary")},
        )
        assert ir.goal == "test"
        assert len(ir.steps) == 1
        assert ir.effects == ["pure"]

    def test_ir_with_config(self) -> None:
        ir = PlanningIR(
            goal="format",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(
                    name="format",
                    skill_id="template.render",
                    sources={"text": IRSource(step="input", port="text")},
                    config={"template": "Results:\n{{text}}"},
                )
            ],
            final_outputs={"formatted": IROutputRef(step="format", port="rendered")},
        )
        assert ir.steps[0].config["template"] == "Results:\n{{text}}"

    def test_ir_default_type(self) -> None:
        inp = IRInput(name="text")
        assert inp.type == "string"

    def test_ir_default_version(self) -> None:
        step = IRStep(name="s", skill_id="text.summarize.v1")
        assert step.version == "1.0.0"

    def test_ir_binding_source(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            bindings=[IRBinding(name="clean_text", source=IRSource(step="input", port="text"))],
            steps=[IRStep(name="call", skill_id="text.summarize.v1", sources={"text": IRSource(binding="clean_text")})],
            final_outputs={"summary": IROutputRef(step="call", port="summary")},
        )
        assert ir.bindings[0].name == "clean_text"
        assert ir.steps[0].sources["text"].binding == "clean_text"


# ── Compiler happy-path tests ──────────────────────────────────────


class TestCompilerHappyPath:
    def test_single_skill_plan(self) -> None:
        ir = PlanningIR(
            goal="summarize text",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(
                    name="call",
                    skill_id="text.summarize.v1",
                    sources={"text": IRSource(step="input", port="text")},
                )
            ],
            final_outputs={"summary": IROutputRef(step="call", port="summary")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert glue.goal == "summarize text"
        assert len(glue.graph.nodes) == 1
        assert glue.graph.nodes[0].id == "call"
        assert glue.graph.nodes[0].op == "skill.invoke"
        assert glue.graph.nodes[0].config["skill_id"] == "text.summarize.v1"
        assert len(glue.graph.edges) == 1
        assert glue.graph.edges[0].from_ == "input.text"
        assert glue.graph.edges[0].to == "call.text"
        assert glue.graph.outputs == {"summary": "call.summary"}
        assert glue.effects == ["llm_inference"]

    def test_chain_plan(self) -> None:
        ir = PlanningIR(
            goal="normalize and summarize",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(
                    name="normalize",
                    skill_id="text.normalize.v1",
                    sources={"text": IRSource(step="input", port="text")},
                ),
                IRStep(
                    name="summarize",
                    skill_id="text.summarize.v1",
                    sources={"text": IRSource(step="normalize", port="normalized")},
                ),
            ],
            final_outputs={"summary": IROutputRef(step="summarize", port="summary")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert len(glue.graph.nodes) == 2
        assert len(glue.graph.edges) == 2

        edge_addrs = [(e.from_, e.to) for e in glue.graph.edges]
        assert ("input.text", "normalize.text") in edge_addrs
        assert ("normalize.normalized", "summarize.text") in edge_addrs

    def test_multi_output_plan(self) -> None:
        ir = PlanningIR(
            goal="normalize and extract keywords",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(
                    name="normalize",
                    skill_id="text.normalize.v1",
                    sources={"text": IRSource(step="input", port="text")},
                ),
                IRStep(
                    name="extract",
                    skill_id="text.extract_keywords.v1",
                    sources={"text": IRSource(step="normalize", port="normalized")},
                ),
            ],
            final_outputs={
                "normalized": IROutputRef(step="normalize", port="normalized"),
                "keywords": IROutputRef(step="extract", port="keywords"),
            },
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert len(glue.outputs) == 2
        assert glue.graph.outputs["normalized"] == "normalize.normalized"
        assert glue.graph.outputs["keywords"] == "extract.keywords"

    def test_template_render_is_primitive_op(self) -> None:
        ir = PlanningIR(
            goal="format with header",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(
                    name="extract",
                    skill_id="text.extract_keywords.v1",
                    sources={"text": IRSource(step="input", port="text")},
                ),
                IRStep(
                    name="format",
                    skill_id="template.render",
                    sources={"text": IRSource(step="extract", port="keywords")},
                    config={"template": "Results:\n{{text}}"},
                ),
            ],
            final_outputs={"formatted": IROutputRef(step="format", port="rendered")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        fmt_node = glue.graph.nodes[1]
        assert fmt_node.op == "template.render"
        assert fmt_node.config["template"] == "Results:\n{{text}}"
        # No skill_id in config for primitive ops
        assert "skill_id" not in fmt_node.config

    def test_compiled_graph_validates(self) -> None:
        ir = PlanningIR(
            goal="extract keywords",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(
                    name="extract",
                    skill_id="text.extract_keywords.v1",
                    sources={"text": IRSource(step="input", port="text")},
                )
            ],
            final_outputs={"keywords": IROutputRef(step="extract", port="keywords")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)  # Should not raise

    def test_fan_out_plan(self) -> None:
        """Two steps sourcing from the same upstream output."""
        ir = PlanningIR(
            goal="summarize and extract keywords",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(
                    name="normalize",
                    skill_id="text.normalize.v1",
                    sources={"text": IRSource(step="input", port="text")},
                ),
                IRStep(
                    name="summarize",
                    skill_id="text.summarize.v1",
                    sources={"text": IRSource(step="normalize", port="normalized")},
                ),
                IRStep(
                    name="extract",
                    skill_id="text.extract_keywords.v1",
                    sources={"text": IRSource(step="normalize", port="normalized")},
                ),
            ],
            final_outputs={
                "summary": IROutputRef(step="summarize", port="summary"),
                "keywords": IROutputRef(step="extract", port="keywords"),
            },
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert len(glue.graph.nodes) == 3
        assert len(glue.graph.edges) == 3
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

    def test_binding_alias_compiles(self) -> None:
        ir = PlanningIR(
            goal="summarize text",
            inputs=[IRInput(name="text", type="union<string, object>")],
            bindings=[IRBinding(name="source_text", source=IRSource(step="input", port="text"))],
            steps=[
                IRStep(
                    name="call",
                    skill_id="text.summarize.v1",
                    sources={"text": IRSource(binding="source_text")},
                )
            ],
            final_outputs={"summary": IROutputRef(step="call", port="summary")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert glue.graph.edges[0].from_ == "input.text"
        assert glue.inputs[0].type == "union<string, object>"

    def test_step_when_compiles_to_node_guard(self) -> None:
        ir = PlanningIR(
            goal="conditionally summarize",
            inputs=[IRInput(name="text"), IRInput(name="enabled", type="boolean")],
            steps=[
                IRStep(
                    name="call",
                    skill_id="text.summarize.v1",
                    sources={"text": IRSource(step="input", port="text")},
                    when=IRSource(step="input", port="enabled"),
                )
            ],
            final_outputs={"summary": IROutputRef(step="call", port="summary")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert glue.graph.nodes[0].when == "input.enabled"

    def test_step_unless_compiles_to_negated_guard(self) -> None:
        ir = PlanningIR(
            goal="conditionally summarize",
            inputs=[IRInput(name="text"), IRInput(name="skip", type="boolean")],
            steps=[
                IRStep(
                    name="call",
                    skill_id="text.summarize.v1",
                    sources={"text": IRSource(step="input", port="text")},
                    when=IRSource(step="input", port="skip"),
                    unless=True,
                )
            ],
            final_outputs={"summary": IROutputRef(step="call", port="summary")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert glue.graph.nodes[0].when == "!input.skip"

    def test_loop_block_lowers_to_parallel_map(self) -> None:
        ir = PlanningIR(
            goal="normalize lines",
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
        assert len(glue.graph.nodes) == 1
        node = glue.graph.nodes[0]
        assert node.op == "parallel.map"
        assert node.config["mode"] == "inline_graph"
        assert node.config["max_items"] == 10
        assert node.config["item_inputs"] == ["text"]
        assert glue.graph.outputs["normalized"] == "normalize_each.normalized"

    def test_branch_block_lowers_to_guarded_steps_and_merge(self) -> None:
        ir = PlanningIR(
            goal="conditionally format",
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
        ids = [node.id for node in glue.graph.nodes]
        assert "format_branch_then_then_render" in ids
        assert "format_branch_else_else_render" in ids
        assert "format_branch_merge_rendered" in ids
        node_map = {node.id: node for node in glue.graph.nodes}
        assert node_map["format_branch_then_then_render"].when == "input.enabled"
        assert node_map["format_branch_else_else_render"].when == "!input.enabled"
        assert node_map["format_branch_merge_rendered"].op == "fallback.try"
        assert glue.graph.outputs["rendered"] == "format_branch_merge_rendered.result"


# ── Compiler error tests ───────────────────────────────────────────


class TestCompilerErrors:
    def test_empty_steps(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[],
            final_outputs={"x": IROutputRef(step="a", port="b")},
        )
        with pytest.raises(EmptyStepsError):
            compile_ir(ir)

    def test_duplicate_step_name(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="dup", skill_id="text.normalize.v1",
                       sources={"text": IRSource(step="input", port="text")}),
                IRStep(name="dup", skill_id="text.summarize.v1",
                       sources={"text": IRSource(step="input", port="text")}),
            ],
            final_outputs={"x": IROutputRef(step="dup", port="y")},
        )
        with pytest.raises(DuplicateStepError, match="dup"):
            compile_ir(ir)

    def test_unknown_source_step(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="call", skill_id="text.summarize.v1",
                       sources={"text": IRSource(step="ghost", port="out")}),
            ],
            final_outputs={"x": IROutputRef(step="call", port="y")},
        )
        with pytest.raises(UnknownSourceStepError, match="ghost"):
            compile_ir(ir)

    def test_unknown_output_step(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="call", skill_id="text.summarize.v1",
                       sources={"text": IRSource(step="input", port="text")}),
            ],
            final_outputs={"x": IROutputRef(step="ghost", port="y")},
        )
        with pytest.raises(UnknownOutputStepError, match="ghost"):
            compile_ir(ir)

    def test_unknown_graph_input(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="call", skill_id="text.summarize.v1",
                       sources={"text": IRSource(step="input", port="missing")}),
            ],
            final_outputs={"x": IROutputRef(step="call", port="y")},
        )
        with pytest.raises(UnknownInputError, match="missing"):
            compile_ir(ir)

    def test_invalid_effect(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="call", skill_id="text.summarize.v1",
                       sources={"text": IRSource(step="input", port="text")}),
            ],
            final_outputs={"x": IROutputRef(step="call", port="y")},
            effects=["teleportation"],
        )
        with pytest.raises(InvalidEffectError, match="teleportation"):
            compile_ir(ir)

    def test_self_loop(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="call", skill_id="text.summarize.v1",
                       sources={"text": IRSource(step="call", port="summary")}),
            ],
            final_outputs={"x": IROutputRef(step="call", port="y")},
        )
        with pytest.raises(SelfLoopError, match="call"):
            compile_ir(ir)

    def test_cycle_between_two_steps(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="a", skill_id="text.normalize.v1",
                       sources={"text": IRSource(step="b", port="out")}),
                IRStep(name="b", skill_id="text.summarize.v1",
                       sources={"text": IRSource(step="a", port="out")}),
            ],
            final_outputs={"x": IROutputRef(step="a", port="y")},
        )
        with pytest.raises(CycleError):
            compile_ir(ir)

    def test_unknown_binding(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(
                    name="call",
                    skill_id="text.summarize.v1",
                    sources={"text": IRSource(binding="ghost")},
                ),
            ],
            final_outputs={"x": IROutputRef(step="call", port="y")},
        )
        with pytest.raises(UnknownBindingError, match="ghost"):
            compile_ir(ir)

    def test_duplicate_binding_name(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            bindings=[
                IRBinding(name="alias", source=IRSource(step="input", port="text")),
                IRBinding(name="alias", source=IRSource(step="input", port="text")),
            ],
            steps=[
                IRStep(name="call", skill_id="text.summarize.v1",
                       sources={"text": IRSource(binding="alias")}),
            ],
            final_outputs={"x": IROutputRef(step="call", port="y")},
        )
        with pytest.raises(DuplicateBindingError, match="alias"):
            compile_ir(ir)

    def test_blocks_are_explicitly_unsupported(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="call", skill_id="text.normalize.v1",
                       sources={"text": IRSource(step="input", port="text")}),
            ],
            blocks=[
                IRBlock(
                    name="local_fn",
                    kind="function",
                )
            ],
            final_outputs={"x": IROutputRef(step="call", port="normalized")},
        )
        with pytest.raises(UnsupportedControlFlowError, match="function"):
            compile_ir(ir)

    def test_loop_block_requires_collection(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="items", type="array<string>")],
            steps=[],
            blocks=[
                IRBlock(
                    name="loop_it",
                    kind="loop",
                    inputs={"text": IRSource(binding="item")},
                    steps=[IRStep(name="normalize", skill_id="text.normalize.v1",
                                  sources={"text": IRSource(step="input", port="text")})],
                    final_outputs={"normalized": IROutputRef(step="normalize", port="normalized")},
                )
            ],
            final_outputs={"normalized": IROutputRef(step="loop_it", port="normalized")},
        )
        with pytest.raises(CompilerError, match="missing collection source"):
            compile_ir(ir)

    def test_branch_block_requires_matching_outputs(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text"), IRInput(name="enabled", type="boolean")],
            steps=[],
            blocks=[
                IRBlock(
                    name="b",
                    kind="branch",
                    condition=IRSource(step="input", port="enabled"),
                    inputs={"text": IRSource(step="input", port="text")},
                    then_steps=[IRStep(name="t", skill_id="template.render",
                                       sources={"text": IRSource(step="input", port="text")},
                                       config={"template": "{{text}}"})],
                    else_steps=[IRStep(name="e", skill_id="template.render",
                                       sources={"text": IRSource(step="input", port="text")},
                                       config={"template": "{{text}}"})],
                    then_outputs={"rendered": IROutputRef(step="t", port="rendered")},
                    else_outputs={"other": IROutputRef(step="e", port="rendered")},
                )
            ],
            final_outputs={"rendered": IROutputRef(step="b", port="rendered")},
        )
        with pytest.raises(CompilerError, match="identical keys"):
            compile_ir(ir)

    def test_compiler_error_has_phase(self) -> None:
        err = DuplicateStepError("foo")
        assert err.phase == "validate_ir"
        assert err.details["step_name"] == "foo"


# ── IR parser tests ────────────────────────────────────────────────


class TestIRParser:
    def test_parse_valid_ir(self) -> None:
        data = {
            "inputs": [{"name": "text", "type": "string"}],
            "steps": [
                {
                    "name": "call",
                    "skill_id": "text.summarize.v1",
                    "version": "1.0.0",
                    "sources": {"text": {"step": "input", "port": "text"}},
                }
            ],
            "final_outputs": {"summary": {"step": "call", "port": "summary"}},
            "effects": ["llm_inference"],
        }
        ir = parse_ir_output(json.dumps(data), goal="summarize")
        assert ir.goal == "summarize"
        assert len(ir.steps) == 1
        assert ir.steps[0].name == "call"

    def test_parse_from_code_fence(self) -> None:
        data = {
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "c", "skill_id": "text.normalize.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"normalized": {"step": "c", "port": "normalized"}},
        }
        raw = f"```json\n{json.dumps(data)}\n```"
        ir = parse_ir_output(raw, goal="test")
        assert ir.steps[0].name == "c"

    def test_parse_missing_keys(self) -> None:
        with pytest.raises(IRParseError, match="Missing required keys"):
            parse_ir_output('{"inputs": []}', goal="test")

    def test_parse_invalid_json(self) -> None:
        with pytest.raises(IRParseError, match="Invalid JSON"):
            parse_ir_output("not json at all", goal="test")

    def test_parse_non_object(self) -> None:
        with pytest.raises(IRParseError, match="Expected JSON object"):
            parse_ir_output("[1,2,3]", goal="test")

    def test_parse_defaults(self) -> None:
        data = {
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "c", "skill_id": "text.normalize.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"out": {"step": "c", "port": "normalized"}},
        }
        ir = parse_ir_output(json.dumps(data), goal="test")
        assert ir.steps[0].version == "1.0.0"
        assert ir.effects == ["pure"]
        assert ir.inputs[0].type == "string"

    def test_parse_binding_shorthand(self) -> None:
        data = {
            "inputs": [{"name": "text"}],
            "bindings": [{"name": "source_text", "source": "input.text"}],
            "steps": [
                {"name": "c", "skill_id": "text.normalize.v1",
                 "sources": {"text": "$source_text"}}
            ],
            "final_outputs": {"out": {"step": "c", "port": "normalized"}},
        }
        ir = parse_ir_output(json.dumps(data), goal="test")
        assert ir.bindings[0].source.step == "input"
        assert ir.steps[0].sources["text"].binding == "source_text"

    def test_parse_blocks(self) -> None:
        data = {
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "c", "skill_id": "text.normalize.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "blocks": [
                {
                    "name": "loop_block",
                    "kind": "loop",
                    "collection": "input.text",
                    "steps": [
                        {"name": "inner", "skill_id": "text.normalize.v1", "sources": {"text": "input.text"}}
                    ],
                    "final_outputs": {"normalized": "inner.normalized"},
                }
            ],
            "final_outputs": {"out": {"step": "c", "port": "normalized"}},
        }
        ir = parse_ir_output(json.dumps(data), goal="test")
        assert ir.blocks[0].kind == "loop"
        assert ir.blocks[0].collection is not None
        assert ir.blocks[0].final_outputs["normalized"].step == "inner"

    def test_parse_branch_block(self) -> None:
        data = {
            "inputs": [{"name": "text"}, {"name": "enabled", "type": "boolean"}],
            "steps": [],
            "blocks": [
                {
                    "name": "format_branch",
                    "kind": "branch",
                    "condition": "input.enabled",
                    "inputs": {"text": "input.text"},
                    "then_steps": [
                        {"name": "t", "skill_id": "template.render", "sources": {"text": "input.text"}, "config": {"template": "then:{{text}}"}}
                    ],
                    "else_steps": [
                        {"name": "e", "skill_id": "template.render", "sources": {"text": "input.text"}, "config": {"template": "else:{{text}}"}}
                    ],
                    "then_outputs": {"rendered": "t.rendered"},
                    "else_outputs": {"rendered": "e.rendered"},
                }
            ],
            "final_outputs": {"rendered": {"step": "format_branch", "port": "rendered"}},
        }
        ir = parse_ir_output(json.dumps(data), goal="test")
        assert ir.blocks[0].kind == "branch"
        assert ir.blocks[0].condition is not None
        assert ir.blocks[0].then_outputs["rendered"].step == "t"

    def test_parse_when_and_unless(self) -> None:
        data = {
            "inputs": [{"name": "text"}, {"name": "enabled", "type": "boolean"}],
            "steps": [
                {
                    "name": "c",
                    "skill_id": "text.normalize.v1",
                    "sources": {"text": {"step": "input", "port": "text"}},
                    "when": "input.enabled",
                    "unless": True,
                }
            ],
            "final_outputs": {"out": {"step": "c", "port": "normalized"}},
        }
        ir = parse_ir_output(json.dumps(data), goal="test")
        assert ir.steps[0].when is not None
        assert ir.steps[0].when.step == "input"
        assert ir.steps[0].when.port == "enabled"
        assert ir.steps[0].unless is True

    def test_roundtrip_parse_compile(self) -> None:
        """Parse IR from JSON, compile to GlueGraph, validate."""
        data = {
            "inputs": [{"name": "text", "type": "string"}],
            "steps": [
                {
                    "name": "extract",
                    "skill_id": "text.extract_keywords.v1",
                    "version": "1.0.0",
                    "sources": {"text": {"step": "input", "port": "text"}},
                },
                {
                    "name": "format",
                    "skill_id": "template.render",
                    "version": "1.0.0",
                    "sources": {"text": {"step": "extract", "port": "keywords"}},
                    "config": {"template": "Results:\n{{text}}"},
                },
            ],
            "final_outputs": {"formatted": {"step": "format", "port": "rendered"}},
            "effects": ["llm_inference"],
        }
        ir = parse_ir_output(json.dumps(data), goal="format with header")
        glue = compile_ir(ir)
        assert len(glue.graph.nodes) == 2
        assert glue.graph.nodes[1].op == "template.render"
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)


# ── IR prompt tests ────────────────────────────────────────────────


class TestIRPrompt:
    def test_prompt_includes_goal(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test goal", candidates=[]))
        assert "test goal" in ctx

    def test_prompt_has_ir_version(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "ir-v" in ctx

    def test_prompt_has_steps_schema(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert '"steps"' in ctx
        assert '"final_outputs"' in ctx
        assert '"sources"' in ctx

    def test_prompt_has_composition_policy(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "STEP COUNT" in ctx or "COMPOSITION POLICY" in ctx

    def test_prompt_has_constants_rule(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "template.render" in ctx
        assert "NEVER create graph inputs for constants" in ctx

    def test_system_message(self) -> None:
        msg = get_ir_system_message()
        assert "plan designer" in msg
        assert "JSON" in msg


# ── IR backend integration tests ───────────────────────────────────


class TestIRBackend:
    def test_backend_with_echo_provider(self) -> None:
        """Integration: EchoLLMProvider → IR parse → compile → validate."""
        from graphsmith.planner.ir_backend import IRPlannerBackend

        # Build a provider that echoes valid IR
        ir_json = json.dumps({
            "inputs": [{"name": "text", "type": "string"}],
            "steps": [
                {
                    "name": "extract",
                    "skill_id": "text.extract_keywords.v1",
                    "version": "1.0.0",
                    "sources": {"text": {"step": "input", "port": "text"}},
                }
            ],
            "final_outputs": {"keywords": {"step": "extract", "port": "keywords"}},
            "effects": ["llm_inference"],
        })

        class FixedProvider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                return ir_json

        backend = IRPlannerBackend(FixedProvider())  # type: ignore[arg-type]
        request = PlanRequest(goal="extract keywords", candidates=[])
        result = backend.compose(request)

        assert result.status == "success"
        assert result.graph is not None
        assert len(result.graph.graph.nodes) == 1
        assert result.graph.graph.outputs["keywords"] == "extract.keywords"

    def test_backend_handles_parse_error(self) -> None:
        from graphsmith.planner.ir_backend import IRPlannerBackend

        class BadProvider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                return "not json"

        backend = IRPlannerBackend(BadProvider())  # type: ignore[arg-type]
        request = PlanRequest(goal="test", candidates=[])
        result = backend.compose(request)

        assert result.status == "failure"
        assert any("ir_parser" in h.node_id for h in result.holes)

    def test_backend_handles_compiler_error(self) -> None:
        from graphsmith.planner.ir_backend import IRPlannerBackend

        # Valid JSON but IR has a self-loop
        bad_ir = json.dumps({
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "loop", "skill_id": "text.normalize.v1",
                 "sources": {"text": {"step": "loop", "port": "normalized"}}}
            ],
            "final_outputs": {"out": {"step": "loop", "port": "normalized"}},
        })

        class LoopProvider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                return bad_ir

        backend = IRPlannerBackend(LoopProvider())  # type: ignore[arg-type]
        request = PlanRequest(goal="test", candidates=[])
        result = backend.compose(request)

        assert result.status == "failure"
        assert any("compiler" in h.node_id for h in result.holes)

    def test_backend_handles_provider_exception(self) -> None:
        from graphsmith.exceptions import ProviderError
        from graphsmith.planner.ir_backend import IRPlannerBackend

        class CrashProvider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                raise ProviderError("rate limit exceeded")

        backend = IRPlannerBackend(CrashProvider())  # type: ignore[arg-type]
        request = PlanRequest(goal="test", candidates=[])
        result = backend.compose(request)

        assert result.status == "failure"
        assert any("provider" in h.node_id for h in result.holes)
