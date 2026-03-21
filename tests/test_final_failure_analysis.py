"""Tests for IR Sprint 5: final failure analysis fixes."""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.compiler import _normalize_type, compile_ir
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.planner.ir import IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.ir_scorer import score_candidate
from graphsmith.validator import validate_skill_package


# ── Compiler: input type normalization ─────────────────────────────


class TestInputTypeNormalization:
    def test_valid_type_unchanged(self) -> None:
        assert _normalize_type("string") == "string"
        assert _normalize_type("integer") == "integer"
        assert _normalize_type("object") == "object"

    def test_invalid_type_becomes_string(self) -> None:
        assert _normalize_type("json") == "string"
        assert _normalize_type("text") == "string"
        assert _normalize_type("any") == "string"
        assert _normalize_type("JSON") == "string"

    def test_parameterized_types_preserved(self) -> None:
        assert _normalize_type("array<string>") == "array<string>"
        assert _normalize_type("optional<integer>") == "optional<integer>"

    def test_json_input_type_compiles_and_validates(self) -> None:
        """The exact failure: LLM declares input type as 'json'."""
        ir = PlanningIR(
            goal="reshape json",
            inputs=[IRInput(name="raw_json", type="json")],
            steps=[
                IRStep(
                    name="reshape",
                    skill_id="json.reshape.v1",
                    sources={"raw_json": IRSource(step="input", port="raw_json")},
                )
            ],
            final_outputs={"selected": IROutputRef(step="reshape", port="selected")},
        )
        glue = compile_ir(ir)
        # Type should be normalized to "string"
        assert glue.inputs[0].type == "string"
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)  # Should not raise


# ── Header goal: template.render equivalence ───────────────────────


class TestHeaderTemplateRenderEquivalence:
    def test_template_render_for_header_compiles(self) -> None:
        """template.render is a valid approach for header goals."""
        ir = PlanningIR(
            goal="extract keywords and add a header saying Results",
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
            final_outputs={"rendered": IROutputRef(step="format", port="rendered")},
            effects=["llm_inference"],
        )
        glue = compile_ir(ir)
        assert len(glue.graph.nodes) == 2
        assert glue.graph.nodes[1].op == "template.render"
        assert glue.graph.outputs["rendered"] == "format.rendered"
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

    def test_scorer_does_not_penalize_template_render_for_header(self) -> None:
        """template.render should not be penalized when goal says 'header'."""
        ir = PlanningIR(
            goal="add header",
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
        score = score_candidate(ir, "extract keywords and add a header saying Results")
        penalty_reasons = [r for r, _ in score.penalties]
        assert not any("unnecessary_formatting" in r for r in penalty_reasons)

    def test_prefix_lines_also_valid_for_header(self) -> None:
        """prefix_lines is equally valid for header goals."""
        ir = PlanningIR(
            goal="add header",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="extract", skill_id="text.extract_keywords.v1",
                       sources={"text": IRSource(step="input", port="text")}),
                IRStep(name="format", skill_id="text.prefix_lines.v1",
                       sources={"text": IRSource(step="extract", port="keywords")}),
            ],
            final_outputs={"prefixed": IROutputRef(step="format", port="prefixed")},
            effects=["llm_inference"],
        )
        score = score_candidate(ir, "extract keywords and add a header saying Results")
        penalty_reasons = [r for r, _ in score.penalties]
        assert not any("unnecessary_formatting" in r for r in penalty_reasons)


# ── Eval spec: acceptable outputs ──────────────────────────────────


class TestEvalSpecAdjustments:
    def test_c04_accepts_rendered(self) -> None:
        """c04 eval goal should accept 'rendered' as an output name."""
        import json
        from pathlib import Path
        data = json.loads(Path("evaluation/challenge_goals/c04_keywords_with_prefix.json").read_text())
        acceptable = data["acceptable_output_names"][0]
        assert "rendered" in acceptable
        assert "prefixed" in acceptable
        assert "formatted" in acceptable

    def test_c04_does_not_require_prefix_lines(self) -> None:
        """c04 should not require text.prefix_lines.v1 specifically."""
        import json
        from pathlib import Path
        data = json.loads(Path("evaluation/challenge_goals/c04_keywords_with_prefix.json").read_text())
        assert "text.prefix_lines.v1" not in data["expected_skills"]
        assert "text.extract_keywords.v1" in data["expected_skills"]

    def test_c09_accepts_rendered(self) -> None:
        """c09 eval goal should accept 'rendered' as an output name."""
        import json
        from pathlib import Path
        data = json.loads(Path("evaluation/challenge_goals/c09_clean_extract_format.json").read_text())
        acceptable = data["acceptable_output_names"][0]
        assert "rendered" in acceptable

    def test_c09_does_not_require_prefix_lines(self) -> None:
        """c09 should not require text.prefix_lines.v1 specifically."""
        import json
        from pathlib import Path
        data = json.loads(Path("evaluation/challenge_goals/c09_clean_extract_format.json").read_text())
        assert "text.prefix_lines.v1" not in data["expected_skills"]
        assert "text.normalize.v1" in data["expected_skills"]
        assert "text.extract_keywords.v1" in data["expected_skills"]


# ── No regression: scorer still works correctly ────────────────────


class TestScorerNoRegression:
    def test_unnecessary_join_lines_still_penalized(self) -> None:
        """join_lines for plain extraction should still be penalized."""
        ir = PlanningIR(
            goal="extract keywords",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="extract", skill_id="text.extract_keywords.v1",
                       sources={"text": IRSource(step="input", port="text")}),
                IRStep(name="format", skill_id="text.join_lines.v1",
                       sources={"lines": IRSource(step="extract", port="keywords")}),
            ],
            final_outputs={"joined": IROutputRef(step="format", port="joined")},
        )
        score = score_candidate(ir, "extract keywords from this text")
        penalty_reasons = [r for r, _ in score.penalties]
        assert any("unnecessary_formatting" in r for r in penalty_reasons)

    def test_join_lines_for_list_goal_not_penalized(self) -> None:
        """join_lines for 'format as list' should not be penalized."""
        ir = PlanningIR(
            goal="format as list",
            inputs=[IRInput(name="text")],
            steps=[
                IRStep(name="extract", skill_id="text.extract_keywords.v1",
                       sources={"text": IRSource(step="input", port="text")}),
                IRStep(name="format", skill_id="text.join_lines.v1",
                       sources={"lines": IRSource(step="extract", port="keywords")}),
            ],
            final_outputs={"joined": IROutputRef(step="format", port="joined")},
        )
        score = score_candidate(ir, "extract keywords and format as a list")
        penalty_reasons = [r for r, _ in score.penalties]
        assert not any("unnecessary_formatting" in r for r in penalty_reasons)
