"""Tests for IR Sprint 2: parser/compiler hardening and semantic prompt changes."""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.compiler import (
    DuplicateStepError,
    compile_ir,
    sanitize_step_name,
)
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.planner.ir import IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.ir_parser import IRParseError, parse_ir_output
from graphsmith.planner.ir_prompt import build_ir_planning_context
from graphsmith.planner.models import PlanRequest
from graphsmith.validator import validate_skill_package


# ── A1: Step name sanitization ─────────────────────────────────────


class TestStepNameSanitization:
    def test_dots_replaced(self) -> None:
        assert sanitize_step_name("text.summarize") == "text_summarize"

    def test_hyphens_replaced(self) -> None:
        assert sanitize_step_name("extract-keywords") == "extract_keywords"

    def test_spaces_replaced(self) -> None:
        assert sanitize_step_name("step 1") == "step_1"

    def test_multiple_special_chars(self) -> None:
        assert sanitize_step_name("text.extract_keywords.v1") == "text_extract_keywords_v1"

    def test_clean_name_unchanged(self) -> None:
        assert sanitize_step_name("extract") == "extract"
        assert sanitize_step_name("normalize") == "normalize"

    def test_uppercase_lowered(self) -> None:
        assert sanitize_step_name("Extract") == "extract"

    def test_empty_falls_back(self) -> None:
        assert sanitize_step_name("...") == "step"
        assert sanitize_step_name("") == "step"

    def test_leading_trailing_underscores_stripped(self) -> None:
        assert sanitize_step_name("_extract_") == "extract"

    def test_consecutive_underscores_collapsed(self) -> None:
        assert sanitize_step_name("text..summarize") == "text_summarize"


class TestStepNameSanitizationInCompiler:
    def test_dot_step_name_compiles_successfully(self) -> None:
        """The exact failure from eval: step named 'text.summarize'."""
        ir = PlanningIR(
            goal="summarize",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(
                    name="text.summarize",
                    skill_id="text.summarize.v1",
                    sources={"text": IRSource(step="input", port="text")},
                )
            ],
            final_outputs={"summary": IROutputRef(step="text.summarize", port="summary")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert glue.graph.nodes[0].id == "text_summarize"
        assert glue.graph.outputs["summary"] == "text_summarize.summary"
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

    def test_hyphenated_step_name(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(
                    name="extract-keywords",
                    skill_id="text.extract_keywords.v1",
                    sources={"text": IRSource(step="input", port="text")},
                )
            ],
            final_outputs={"keywords": IROutputRef(step="extract-keywords", port="keywords")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert glue.graph.nodes[0].id == "extract_keywords"
        assert glue.graph.outputs["keywords"] == "extract_keywords.keywords"

    def test_source_references_remapped(self) -> None:
        """Sources using original step names get remapped to sanitized names."""
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(
                    name="text.normalize",
                    skill_id="text.normalize.v1",
                    sources={"text": IRSource(step="input", port="text")},
                ),
                IRStep(
                    name="text.summarize",
                    skill_id="text.summarize.v1",
                    sources={"text": IRSource(step="text.normalize", port="normalized")},
                ),
            ],
            final_outputs={"summary": IROutputRef(step="text.summarize", port="summary")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert glue.graph.nodes[0].id == "text_normalize"
        assert glue.graph.nodes[1].id == "text_summarize"
        edge_addrs = [(e.from_, e.to) for e in glue.graph.edges]
        assert ("text_normalize.normalized", "text_summarize.text") in edge_addrs

    def test_collision_resolution(self) -> None:
        """Two steps that sanitize to the same name get deterministic suffixes."""
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(
                    name="step.a",
                    skill_id="text.normalize.v1",
                    sources={"text": IRSource(step="input", port="text")},
                ),
                IRStep(
                    name="step-a",
                    skill_id="text.summarize.v1",
                    sources={"text": IRSource(step="step.a", port="normalized")},
                ),
            ],
            final_outputs={"out": IROutputRef(step="step-a", port="summary")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        ids = [n.id for n in glue.graph.nodes]
        assert len(set(ids)) == 2  # no duplicates
        assert ids[0] == "step_a"
        assert ids[1] == "step_a_2"


# ── A2: final_outputs normalization ────────────────────────────────


class TestFinalOutputsNormalization:
    def test_string_shorthand_step_dot_port(self) -> None:
        """'step.port' string form is normalized to object."""
        data = {
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "call", "skill_id": "text.summarize.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"summary": "call.summary"},
            "effects": ["llm_inference"],
        }
        ir = parse_ir_output(json.dumps(data), goal="test")
        assert ir.final_outputs["summary"].step == "call"
        assert ir.final_outputs["summary"].port == "summary"

    def test_bare_step_name_uses_output_name_as_port(self) -> None:
        """Bare step name → port defaults to the output name."""
        data = {
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "summarize", "skill_id": "text.summarize.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"summary": "summarize"},
            "effects": ["llm_inference"],
        }
        ir = parse_ir_output(json.dumps(data), goal="test")
        assert ir.final_outputs["summary"].step == "summarize"
        assert ir.final_outputs["summary"].port == "summary"

    def test_unknown_bare_name_raises(self) -> None:
        data = {
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "call", "skill_id": "text.summarize.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"summary": "ghost"},
        }
        with pytest.raises(IRParseError, match="Failed to build IR"):
            parse_ir_output(json.dumps(data), goal="test")

    def test_source_string_shorthand(self) -> None:
        """Source as 'step.port' string is normalized."""
        data = {
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "normalize", "skill_id": "text.normalize.v1",
                 "sources": {"text": "input.text"}},
                {"name": "summarize", "skill_id": "text.summarize.v1",
                 "sources": {"text": "normalize.normalized"}},
            ],
            "final_outputs": {"summary": {"step": "summarize", "port": "summary"}},
        }
        ir = parse_ir_output(json.dumps(data), goal="test")
        assert ir.steps[0].sources["text"].step == "input"
        assert ir.steps[0].sources["text"].port == "text"
        assert ir.steps[1].sources["text"].step == "normalize"
        assert ir.steps[1].sources["text"].port == "normalized"

    def test_roundtrip_shorthand_compiles(self) -> None:
        """Shorthand final_outputs + source strings → compile → validate."""
        data = {
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "extract", "skill_id": "text.extract_keywords.v1",
                 "sources": {"text": "input.text"}},
            ],
            "final_outputs": {"keywords": "extract.keywords"},
            "effects": ["llm_inference"],
        }
        ir = parse_ir_output(json.dumps(data), goal="test")
        glue = compile_ir(ir)
        assert glue.graph.outputs["keywords"] == "extract.keywords"
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)


# ── B: Semantic prompt tests ───────────────────────────────────────


class TestIRPromptSemantics:
    def test_prompt_has_step_count_guidance(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "STEP COUNT" in ctx

    def test_prompt_says_1_step_for_plain_extraction(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "1 step" in ctx.lower()
        assert "Extract keywords" in ctx
        assert "Find the key topics" in ctx

    def test_prompt_says_no_formatting_without_request(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "do NOT add formatting steps" in ctx

    def test_prompt_has_single_extraction_example(self) -> None:
        """Example 2 shows single-step extraction with no formatting."""
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        # Should have an example with "Extract keywords" goal and 1 step
        assert "single skill — extract keywords" in ctx.lower() or \
               "extract keywords (NO formatting)" in ctx

    def test_prompt_has_step_name_guidance(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "Do NOT use dots or spaces" in ctx

    def test_prompt_version_is_current(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "ir-v" in ctx

    def test_prompt_has_formatting_example_with_list(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "format them as a list" in ctx.lower() or "formatting as list" in ctx.lower()

    def test_prompt_has_header_constant_example(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "header saying Results" in ctx


# ── Integration: parse+compile from LLM-like shorthand ─────────────


class TestShorthandIntegration:
    def test_dot_step_name_with_shorthand_outputs(self) -> None:
        """Combines both hardening features: dot name + string shorthand."""
        data = {
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "text.summarize", "skill_id": "text.summarize.v1",
                 "sources": {"text": "input.text"}},
            ],
            "final_outputs": {"summary": "text.summarize.summary"},
            "effects": ["llm_inference"],
        }
        ir = parse_ir_output(json.dumps(data), goal="test")
        glue = compile_ir(ir)
        assert glue.graph.nodes[0].id == "text_summarize"
        assert glue.graph.outputs["summary"] == "text_summarize.summary"
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

    def test_mixed_shorthand_and_canonical(self) -> None:
        data = {
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "normalize", "skill_id": "text.normalize.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}},
                {"name": "extract", "skill_id": "text.extract_keywords.v1",
                 "sources": {"text": "normalize.normalized"}},
            ],
            "final_outputs": {
                "normalized": {"step": "normalize", "port": "normalized"},
                "keywords": "extract.keywords",
            },
            "effects": ["llm_inference"],
        }
        ir = parse_ir_output(json.dumps(data), goal="test")
        glue = compile_ir(ir)
        assert len(glue.graph.nodes) == 2
        assert glue.graph.outputs["normalized"] == "normalize.normalized"
        assert glue.graph.outputs["keywords"] == "extract.keywords"
