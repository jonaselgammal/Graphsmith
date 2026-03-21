"""Tests for IR Sprint 7: final holdout cleanup."""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.decomposition import (
    DecompositionParseError,
    SemanticDecomposition,
    decompose_deterministic,
    parse_decomposition,
)
from graphsmith.planner.ir import IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.ir_backend import IRPlannerBackend
from graphsmith.planner.ir_scorer import score_candidate
from graphsmith.planner.models import PlanRequest


# ── Fix 1: final_output_names dict normalization ───────────────────


class TestFinalOutputNamesDictNormalization:
    def test_dict_normalized_to_list(self) -> None:
        """LLM returning final_output_names as dict should be handled."""
        raw = json.dumps({
            "content_transforms": ["reshape_json"],
            "presentation": "none",
            "final_output_names": {"reshape_json": "selected"},
        })
        d = parse_decomposition(raw)
        assert d.final_output_names == ["selected"]

    def test_list_unchanged(self) -> None:
        raw = json.dumps({
            "content_transforms": ["extract_keywords"],
            "presentation": "none",
            "final_output_names": ["keywords"],
        })
        d = parse_decomposition(raw)
        assert d.final_output_names == ["keywords"]

    def test_non_list_non_dict_becomes_empty(self) -> None:
        raw = json.dumps({
            "content_transforms": ["extract_keywords"],
            "presentation": "none",
            "final_output_names": "keywords",
        })
        d = parse_decomposition(raw)
        assert d.final_output_names == []


# ── Fix 1b: backend catches all exceptions in decomposition ───────


class TestDecompositionFallback:
    def test_pydantic_error_falls_back_to_deterministic(self) -> None:
        """Pydantic ValidationError in decomposition falls back gracefully."""
        call_count = 0
        ir_json = json.dumps({
            "inputs": [{"name": "raw_json"}],
            "steps": [
                {"name": "reshape", "skill_id": "json.reshape.v1",
                 "sources": {"raw_json": {"step": "input", "port": "raw_json"}}}
            ],
            "final_outputs": {"selected": {"step": "reshape", "port": "selected"}},
        })
        # Return something that will cause a Pydantic error
        bad_decomp = json.dumps({
            "content_transforms": 42,  # not a list
            "presentation": "none",
            "final_output_names": ["selected"],
        })

        class Provider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return bad_decomp
                return ir_json

        backend = IRPlannerBackend(
            Provider(), candidate_count=1, use_decomposition=True,  # type: ignore[arg-type]
        )
        result = backend.compose(PlanRequest(
            goal="Extract the name and value from this JSON", candidates=[],
        ))
        # Should not crash — should fall back to deterministic decomposition
        assert result.status == "success"
        assert backend.last_decomposition is not None


# ── Fix 2: h09 eval spec ──────────────────────────────────────────


class TestH09EvalSpec:
    def test_h09_accepts_rendered(self) -> None:
        import json
        from pathlib import Path
        data = json.loads(Path("evaluation/holdout_goals/h09_normalize_and_format_keywords.json").read_text())
        assert "rendered" in data["acceptable_output_names"][0]

    def test_h09_does_not_require_join_lines(self) -> None:
        import json
        from pathlib import Path
        data = json.loads(Path("evaluation/holdout_goals/h09_normalize_and_format_keywords.json").read_text())
        assert "text.join_lines.v1" not in data["expected_skills"]
        assert "text.normalize.v1" in data["expected_skills"]
        assert "text.extract_keywords.v1" in data["expected_skills"]


# ── Decomposition overreach checks ────────────────────────────────


class TestDecompositionOverreach:
    def test_plain_extraction_no_normalize(self) -> None:
        """'Extract keywords' should NOT require normalize."""
        d = decompose_deterministic("Extract keywords from this text")
        assert "normalize" not in d.content_transforms
        assert d.presentation == "none"

    def test_simple_summarize_no_normalize(self) -> None:
        d = decompose_deterministic("Summarize this text")
        assert "normalize" not in d.content_transforms
        assert d.presentation == "none"

    def test_find_topics_no_formatting(self) -> None:
        d = decompose_deterministic("Find the key topics in this text")
        assert d.presentation == "none"

    def test_nicely_maps_to_list(self) -> None:
        """'format nicely' should map to list, not header."""
        d = decompose_deterministic("Normalize the text, extract keywords, and format them nicely")
        assert d.presentation == "list"


# ── No regression on challenge header cases ────────────────────────


class TestNoRegressionHeaders:
    def test_header_decomposition_unchanged(self) -> None:
        d = decompose_deterministic("Extract keywords and add a header saying Results")
        assert d.presentation == "header"
        assert "rendered" in d.final_output_names

    def test_scorer_template_render_for_header_not_penalized(self) -> None:
        ir = PlanningIR(
            goal="header",
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
        decomp = SemanticDecomposition(
            content_transforms=["extract_keywords"],
            presentation="header",
            final_output_names=["rendered"],
        )
        score = score_candidate(ir, "add a header", decomposition=decomp)
        reasons = [r for r, _ in score.penalties]
        assert not any("decomp_unwanted" in r for r in reasons)
        assert not any("decomp_missing_presentation" in r for r in reasons)
