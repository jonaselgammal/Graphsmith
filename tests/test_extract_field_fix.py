"""Tests for IR Sprint 9: extract_field decomposition fix."""
from __future__ import annotations

import pytest

from graphsmith.planner.decomposition import (
    SemanticDecomposition,
    decompose_deterministic,
)
from graphsmith.planner.ir import IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.ir_scorer import score_candidate


class TestExtractFieldDecomposition:
    def test_extract_value_field(self) -> None:
        """'Parse this JSON and extract the value field' → extract_field."""
        d = decompose_deterministic("Parse this JSON and extract the value field")
        assert "extract_field" in d.content_transforms
        assert "reshape_json" not in d.content_transforms
        assert "value" in d.final_output_names

    def test_reshape_json_unchanged(self) -> None:
        """'Extract the name and value from this JSON' still → reshape_json."""
        d = decompose_deterministic("Extract the name and value from this JSON")
        assert "reshape_json" in d.content_transforms
        assert "selected" in d.final_output_names

    def test_parse_and_reshape(self) -> None:
        """'Parse and reshape JSON data' → reshape_json."""
        d = decompose_deterministic("Parse and reshape JSON data to extract name and value fields")
        assert "reshape_json" in d.content_transforms
        assert "extract_field" not in d.content_transforms

    def test_extract_field_not_confused_with_keywords(self) -> None:
        """extract_field should not also produce extract_keywords."""
        d = decompose_deterministic("Parse this JSON and extract the value field")
        assert "extract_keywords" not in d.content_transforms


class TestScorerExtractFieldConsistency:
    def _make_ir(self, skill_id: str, output_name: str, output_port: str) -> PlanningIR:
        return PlanningIR(
            goal="test",
            inputs=[IRInput(name="raw_json")],
            steps=[
                IRStep(name="op", skill_id=skill_id,
                       sources={"raw_json": IRSource(step="input", port="raw_json")}),
            ],
            final_outputs={output_name: IROutputRef(step="op", port=output_port)},
        )

    def test_extract_field_rewarded_with_decomp(self) -> None:
        decomp = SemanticDecomposition(
            content_transforms=["extract_field"],
            presentation="none",
            final_output_names=["value"],
        )
        ir = self._make_ir("json.extract_field.v1", "value", "value")
        score = score_candidate(ir, "extract the value field", decomposition=decomp)
        rewards = [r for r, _ in score.rewards]
        assert any("decomp_has_transform: extract_field" in r for r in rewards)
        assert any("decomp_output_match: value" in r for r in rewards)

    def test_reshape_penalized_when_decomp_says_extract_field(self) -> None:
        decomp = SemanticDecomposition(
            content_transforms=["extract_field"],
            presentation="none",
            final_output_names=["value"],
        )
        ir = self._make_ir("json.reshape.v1", "selected", "selected")
        score = score_candidate(ir, "extract the value field", decomposition=decomp)
        penalties = [r for r, _ in score.penalties]
        assert any("decomp_missing_transform: extract_field" in r for r in penalties)

    def test_extract_field_outscores_reshape_for_value_goal(self) -> None:
        decomp = SemanticDecomposition(
            content_transforms=["extract_field"],
            presentation="none",
            final_output_names=["value"],
        )
        ir_good = self._make_ir("json.extract_field.v1", "value", "value")
        ir_bad = self._make_ir("json.reshape.v1", "selected", "selected")
        score_good = score_candidate(ir_good, "extract the value field", decomposition=decomp)
        score_bad = score_candidate(ir_bad, "extract the value field", decomposition=decomp)
        assert score_good.total > score_bad.total


class TestNoRegressionOnOtherJsonGoals:
    def test_reshape_goal_still_works(self) -> None:
        d = decompose_deterministic("Extract the name and value from this JSON")
        assert "reshape_json" in d.content_transforms

    def test_simple_json_parse(self) -> None:
        """'parse json' without 'reshape' defaults to extract_field."""
        d = decompose_deterministic("Parse this JSON data")
        assert "extract_field" in d.content_transforms or "reshape_json" in d.content_transforms
