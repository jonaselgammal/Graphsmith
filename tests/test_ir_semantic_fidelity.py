"""Tests for IR Sprint 3: semantic planning fidelity.

These tests verify that the IR prompt and backend produce semantically
correct plans for key goal patterns.
"""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.compiler import compile_ir, _normalize_skill_id
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.planner.ir import IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.ir_parser import parse_ir_output
from graphsmith.planner.ir_prompt import build_ir_planning_context
from graphsmith.planner.models import PlanRequest
from graphsmith.validator import validate_skill_package


# ── Prompt content tests ───────────────────────────────────────────


class TestIRPromptSemanticContent:
    def test_prompt_version_ir_v3(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "ir-v3" in ctx

    def test_has_output_naming_guidance(self) -> None:
        """Prompt must teach correct output naming with examples."""
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "FINAL OUTPUT NAMING" in ctx
        assert "output_ports" in ctx.lower() or "output port" in ctx.lower()

    def test_has_wrong_right_output_examples(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "WRONG:" in ctx
        assert "RIGHT:" in ctx
        assert "cleaned_text" in ctx  # common wrong name

    def test_has_paraphrase_mapping(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "tidy up" in ctx.lower()
        assert "text.normalize.v1" in ctx
        assert "find topics" in ctx.lower()
        assert "capitalize" in ctx.lower()
        assert "text.title_case.v1" in ctx

    def test_has_cleanup_capitalize_example(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "capitalize each word" in ctx.lower() or "capitalize" in ctx.lower()
        assert '"titled"' in ctx

    def test_has_skill_id_version_rule(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "@version" in ctx or "@1.0.0" in ctx

    def test_says_must_include_normalize_for_clean(self) -> None:
        ctx = build_ir_planning_context(PlanRequest(goal="test", candidates=[]))
        assert "MUST include a normalize step" in ctx


# ── Correct IR structure tests ─────────────────────────────────────


class TestCorrectIRPlans:
    """Verify that correct IR plans compile and validate."""

    def test_plain_keyword_extraction(self) -> None:
        """'Extract keywords' → 1 step, output 'keywords'."""
        ir = PlanningIR(
            goal="extract keywords",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="extract", skill_id="text.extract_keywords.v1",
                       sources={"text": IRSource(step="input", port="text")}),
            ],
            final_outputs={"keywords": IROutputRef(step="extract", port="keywords")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert len(glue.graph.nodes) == 1
        assert "keywords" in glue.graph.outputs
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

    def test_topic_phrasing_same_as_keywords(self) -> None:
        """'Find the key topics' → same as extract keywords."""
        ir = PlanningIR(
            goal="find the key topics",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="extract", skill_id="text.extract_keywords.v1",
                       sources={"text": IRSource(step="input", port="text")}),
            ],
            final_outputs={"keywords": IROutputRef(step="extract", port="keywords")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert len(glue.graph.nodes) == 1
        assert "keywords" in glue.graph.outputs

    def test_tidy_and_topics(self) -> None:
        """'Tidy up and find topics' → normalize + extract, no formatting."""
        ir = PlanningIR(
            goal="tidy up and find topics",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="normalize", skill_id="text.normalize.v1",
                       sources={"text": IRSource(step="input", port="text")}),
                IRStep(name="extract", skill_id="text.extract_keywords.v1",
                       sources={"text": IRSource(step="normalize", port="normalized")}),
            ],
            final_outputs={
                "normalized": IROutputRef(step="normalize", port="normalized"),
                "keywords": IROutputRef(step="extract", port="keywords"),
            },
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert len(glue.graph.nodes) == 2
        assert "normalized" in glue.graph.outputs
        assert "keywords" in glue.graph.outputs
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

    def test_cleanup_and_capitalize(self) -> None:
        """'Clean up and capitalize' → normalize + title_case, output 'titled'."""
        ir = PlanningIR(
            goal="clean up and capitalize",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="normalize", skill_id="text.normalize.v1",
                       sources={"text": IRSource(step="input", port="text")}),
                IRStep(name="title", skill_id="text.title_case.v1",
                       sources={"text": IRSource(step="normalize", port="normalized")}),
            ],
            final_outputs={"titled": IROutputRef(step="title", port="titled")},
            effects=["pure"],
        )
        glue = compile_ir(ir)
        assert len(glue.graph.nodes) == 2
        assert glue.graph.outputs["titled"] == "title.titled"
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

    def test_extract_plus_header(self) -> None:
        """'Extract keywords and add header' → extract + template.render."""
        ir = PlanningIR(
            goal="extract keywords and add header",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="extract", skill_id="text.extract_keywords.v1",
                       sources={"text": IRSource(step="input", port="text")}),
                IRStep(name="format", skill_id="template.render",
                       sources={"text": IRSource(step="extract", port="keywords")},
                       config={"template": "Results:\n{{text}}"}),
            ],
            final_outputs={"rendered": IROutputRef(step="format", port="rendered")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert len(glue.graph.nodes) == 2
        assert glue.graph.outputs["rendered"] == "format.rendered"
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

    def test_extract_plus_list_format(self) -> None:
        """'Extract keywords and format as list' → extract + join_lines."""
        ir = PlanningIR(
            goal="extract keywords and format as list",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="extract", skill_id="text.extract_keywords.v1",
                       sources={"text": IRSource(step="input", port="text")}),
                IRStep(name="format", skill_id="text.join_lines.v1",
                       sources={"lines": IRSource(step="extract", port="keywords")}),
            ],
            final_outputs={"joined": IROutputRef(step="format", port="joined")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert len(glue.graph.nodes) == 2
        assert glue.graph.outputs["joined"] == "format.joined"
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

    def test_json_reshape_output_selected(self) -> None:
        """json.reshape.v1 output must be named 'selected'."""
        ir = PlanningIR(
            goal="reshape json",
            inputs=[IRInput(name="raw_json")],
            steps=[
                IRStep(name="reshape", skill_id="json.reshape.v1",
                       sources={"raw_json": IRSource(step="input", port="raw_json")}),
            ],
            final_outputs={"selected": IROutputRef(step="reshape", port="selected")},
        )
        glue = compile_ir(ir)
        assert glue.graph.outputs["selected"] == "reshape.selected"


# ── Compiler skill_id normalization ────────────────────────────────


class TestSkillIdNormalization:
    def test_strip_at_version(self) -> None:
        sid, ver = _normalize_skill_id("text.summarize.v1@1.0.0", "1.0.0")
        assert sid == "text.summarize.v1"
        assert ver == "1.0.0"

    def test_no_at_unchanged(self) -> None:
        sid, ver = _normalize_skill_id("text.summarize.v1", "1.0.0")
        assert sid == "text.summarize.v1"
        assert ver == "1.0.0"

    def test_at_version_used_when_present(self) -> None:
        sid, ver = _normalize_skill_id("text.summarize.v1@2.0.0", "1.0.0")
        assert sid == "text.summarize.v1"
        assert ver == "2.0.0"

    def test_at_version_compiles(self) -> None:
        """skill_id with @version should compile correctly."""
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="call", skill_id="text.summarize.v1@1.0.0",
                       sources={"text": IRSource(step="input", port="text")}),
            ],
            final_outputs={"summary": IROutputRef(step="call", port="summary")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert glue.graph.nodes[0].config["skill_id"] == "text.summarize.v1"

    def test_at_version_roundtrip(self) -> None:
        """Parse IR with @version, compile, validate."""
        data = {
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "summarize", "skill_id": "text.summarize.v1@1.0.0",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"summary": {"step": "summarize", "port": "summary"}},
            "effects": ["llm_inference"],
        }
        ir = parse_ir_output(json.dumps(data), goal="test")
        glue = compile_ir(ir)
        assert glue.graph.nodes[0].config["skill_id"] == "text.summarize.v1"
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)


# ── Parser/compiler hardening still works ──────────────────────────


class TestHardeningNoRegression:
    def test_dot_step_names_still_sanitized(self) -> None:
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="text.normalize", skill_id="text.normalize.v1",
                       sources={"text": IRSource(step="input", port="text")}),
            ],
            final_outputs={"normalized": IROutputRef(step="text.normalize", port="normalized")},
        )
        glue = compile_ir(ir)
        assert glue.graph.nodes[0].id == "text_normalize"

    def test_shorthand_final_outputs_still_work(self) -> None:
        data = {
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "call", "skill_id": "text.normalize.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"normalized": "call.normalized"},
        }
        ir = parse_ir_output(json.dumps(data), goal="test")
        assert ir.final_outputs["normalized"].step == "call"
        assert ir.final_outputs["normalized"].port == "normalized"
