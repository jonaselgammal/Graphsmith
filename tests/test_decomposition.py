"""Tests for IR Sprint 6: semantic decomposition."""
from __future__ import annotations

import json

import pytest

from graphsmith.planner.decomposition import (
    DecompositionParseError,
    SemanticDecomposition,
    build_decomposition_prompt,
    decompose_deterministic,
    parse_decomposition,
)
from graphsmith.planner.ir import IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.ir_backend import IRPlannerBackend
from graphsmith.planner.ir_scorer import ScoreBreakdown, score_candidate
from graphsmith.planner.models import PlanRequest


# ── Decomposition parsing ──────────────────────────────────────────


class TestDecompositionParsing:
    def test_parse_plain_extraction(self) -> None:
        raw = json.dumps({
            "content_transforms": ["extract_keywords"],
            "presentation": "none",
            "final_output_names": ["keywords"],
        })
        d = parse_decomposition(raw)
        assert d.content_transforms == ["extract_keywords"]
        assert d.presentation == "none"
        assert d.final_output_names == ["keywords"]

    def test_parse_list_formatting(self) -> None:
        raw = json.dumps({
            "content_transforms": ["extract_keywords"],
            "presentation": "list",
            "final_output_names": ["joined"],
        })
        d = parse_decomposition(raw)
        assert d.presentation == "list"

    def test_parse_header_goal(self) -> None:
        raw = json.dumps({
            "content_transforms": ["extract_keywords"],
            "presentation": "header",
            "final_output_names": ["rendered"],
        })
        d = parse_decomposition(raw)
        assert d.presentation == "header"

    def test_parse_cleanup_capitalize(self) -> None:
        raw = json.dumps({
            "content_transforms": ["normalize", "title_case"],
            "presentation": "none",
            "final_output_names": ["titled"],
        })
        d = parse_decomposition(raw)
        assert d.content_transforms == ["normalize", "title_case"]

    def test_parse_invalid_json(self) -> None:
        with pytest.raises(DecompositionParseError, match="Invalid JSON"):
            parse_decomposition("not json")

    def test_parse_invalid_presentation_defaults_none(self) -> None:
        raw = json.dumps({
            "content_transforms": ["normalize"],
            "presentation": "fancy",
            "final_output_names": ["normalized"],
        })
        d = parse_decomposition(raw)
        assert d.presentation == "none"

    def test_parse_from_code_fence(self) -> None:
        data = {
            "content_transforms": ["summarize"],
            "presentation": "none",
            "final_output_names": ["summary"],
        }
        raw = f"```json\n{json.dumps(data)}\n```"
        d = parse_decomposition(raw)
        assert d.content_transforms == ["summarize"]


# ── Deterministic decomposition ────────────────────────────────────


class TestDeterministicDecomposition:
    def test_plain_extraction(self) -> None:
        d = decompose_deterministic("Extract keywords from this text")
        assert "extract_keywords" in d.content_transforms
        assert d.presentation == "none"
        assert "keywords" in d.final_output_names

    def test_topic_phrasing(self) -> None:
        d = decompose_deterministic("Find the key topics in this text")
        assert "extract_keywords" in d.content_transforms
        assert d.presentation == "none"

    def test_list_formatting(self) -> None:
        d = decompose_deterministic("Extract keywords and format as a list")
        assert "extract_keywords" in d.content_transforms
        assert d.presentation == "list"
        assert "joined" in d.final_output_names

    def test_header_goal(self) -> None:
        d = decompose_deterministic("Extract keywords and add a header saying Results")
        assert "extract_keywords" in d.content_transforms
        assert d.presentation == "header"
        assert "rendered" in d.final_output_names

    def test_cleanup_and_capitalize(self) -> None:
        d = decompose_deterministic("Clean up this text and capitalize each word")
        assert "normalize" in d.content_transforms
        assert "title_case" in d.content_transforms
        assert d.presentation == "none"

    def test_normalize_and_count(self) -> None:
        d = decompose_deterministic("Normalize this text and count the words")
        assert "normalize" in d.content_transforms
        assert "word_count" in d.content_transforms
        assert "normalized" in d.final_output_names
        assert "count" in d.final_output_names

    def test_json_reshape(self) -> None:
        d = decompose_deterministic("Extract the name and value from this JSON")
        assert "reshape_json" in d.content_transforms
        assert d.presentation == "none"
        assert "selected" in d.final_output_names

    def test_clean_topics_header(self) -> None:
        d = decompose_deterministic("Clean up the text, pull out key topics, and format them with a header")
        assert "normalize" in d.content_transforms
        assert "extract_keywords" in d.content_transforms
        assert d.presentation == "header"
        assert "rendered" in d.final_output_names


# ── Decomposition → IR consistency scoring ─────────────────────────


class TestDecompositionConsistency:
    def _make_ir(self, steps, final_outputs):
        ir_steps = []
        for i, (name, skill_id) in enumerate(steps):
            sources = {"text": IRSource(step="input", port="text")} if i == 0 \
                else {"text": IRSource(step=steps[i-1][0], port="out")}
            ir_steps.append(IRStep(name=name, skill_id=skill_id, sources=sources))
        ir_outs = {n: IROutputRef(step=s, port=p) for n, (s, p) in final_outputs.items()}
        return PlanningIR(
            goal="test", inputs=[IRInput(name="text")],
            steps=ir_steps, final_outputs=ir_outs, effects=["llm_inference"],
        )

    def test_no_presentation_penalizes_formatting(self) -> None:
        """decomp says none → IR with join_lines gets penalized."""
        decomp = SemanticDecomposition(
            content_transforms=["extract_keywords"],
            presentation="none",
            final_output_names=["keywords"],
        )
        ir = self._make_ir(
            [("extract", "text.extract_keywords.v1"), ("format", "text.join_lines.v1")],
            {"joined": ("format", "joined")},
        )
        score = score_candidate(ir, "extract keywords", decomposition=decomp)
        reasons = [r for r, _ in score.penalties]
        assert any("decomp_unwanted_presentation" in r for r in reasons)

    def test_none_presentation_rewards_clean_ir(self) -> None:
        """decomp says none → IR without formatting scores well."""
        decomp = SemanticDecomposition(
            content_transforms=["extract_keywords"],
            presentation="none",
            final_output_names=["keywords"],
        )
        ir = self._make_ir(
            [("extract", "text.extract_keywords.v1")],
            {"keywords": ("extract", "keywords")},
        )
        score = score_candidate(ir, "extract keywords", decomposition=decomp)
        reasons = [r for r, _ in score.penalties]
        assert not any("decomp_unwanted_presentation" in r for r in reasons)
        reward_reasons = [r for r, _ in score.rewards]
        assert any("decomp_has_transform" in r for r in reward_reasons)

    def test_header_decomp_rewards_template_render(self) -> None:
        decomp = SemanticDecomposition(
            content_transforms=["extract_keywords"],
            presentation="header",
            final_output_names=["rendered"],
        )
        ir = self._make_ir(
            [("extract", "text.extract_keywords.v1"), ("format", "template.render")],
            {"rendered": ("format", "rendered")},
        )
        score = score_candidate(ir, "add header", decomposition=decomp)
        reward_reasons = [r for r, _ in score.rewards]
        assert any("decomp_correct_presentation" in r for r in reward_reasons)

    def test_header_decomp_penalizes_join_lines(self) -> None:
        """decomp says header → join_lines gets penalized for missing header."""
        decomp = SemanticDecomposition(
            content_transforms=["extract_keywords"],
            presentation="header",
            final_output_names=["rendered"],
        )
        ir = self._make_ir(
            [("extract", "text.extract_keywords.v1"), ("format", "text.join_lines.v1")],
            {"joined": ("format", "joined")},
        )
        score = score_candidate(ir, "add header", decomposition=decomp)
        reasons = [r for r, _ in score.penalties]
        assert any("decomp_missing_presentation" in r for r in reasons)

    def test_missing_transform_penalized(self) -> None:
        """decomp says normalize required → IR missing it gets penalized."""
        decomp = SemanticDecomposition(
            content_transforms=["normalize", "title_case"],
            presentation="none",
            final_output_names=["titled"],
        )
        ir = self._make_ir(
            [("title", "text.title_case.v1")],
            {"titled": ("title", "titled")},
        )
        score = score_candidate(ir, "clean and capitalize", decomposition=decomp)
        reasons = [r for r, _ in score.penalties]
        assert any("decomp_missing_transform: normalize" in r for r in reasons)

    def test_output_name_match_rewarded(self) -> None:
        decomp = SemanticDecomposition(
            content_transforms=["extract_keywords"],
            presentation="none",
            final_output_names=["keywords"],
        )
        ir = self._make_ir(
            [("extract", "text.extract_keywords.v1")],
            {"keywords": ("extract", "keywords")},
        )
        score = score_candidate(ir, "extract keywords", decomposition=decomp)
        reward_reasons = [r for r, _ in score.rewards]
        assert any("decomp_output_match: keywords" in r for r in reward_reasons)

    def test_output_name_mismatch_penalized(self) -> None:
        decomp = SemanticDecomposition(
            content_transforms=["normalize", "word_count"],
            presentation="none",
            final_output_names=["normalized", "count"],
        )
        ir = self._make_ir(
            [("normalize", "text.normalize.v1"), ("wc", "text.word_count.v1")],
            {"count": ("wc", "count")},  # missing 'normalized'
        )
        score = score_candidate(ir, "normalize and count", decomposition=decomp)
        reasons = [r for r, _ in score.penalties]
        assert any("decomp_output_missing: normalized" in r for r in reasons)


# ── Decomposition prompt ───────────────────────────────────────────


class TestDecompositionPrompt:
    def test_prompt_contains_goal(self) -> None:
        prompt = build_decomposition_prompt(PlanRequest(goal="test goal", candidates=[]))
        assert "test goal" in prompt

    def test_prompt_has_examples(self) -> None:
        prompt = build_decomposition_prompt(PlanRequest(goal="test", candidates=[]))
        assert "extract_keywords" in prompt
        assert '"none"' in prompt
        assert '"header"' in prompt
        assert '"list"' in prompt


# ── Backend integration with decomposition ─────────────────────────


class TestDecompositionBackendIntegration:
    def test_decomposition_disabled_by_default(self) -> None:
        ir_json = json.dumps({
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "extract", "skill_id": "text.extract_keywords.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"keywords": {"step": "extract", "port": "keywords"}},
            "effects": ["llm_inference"],
        })

        class FixedProvider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                return ir_json

        backend = IRPlannerBackend(FixedProvider(), candidate_count=1)  # type: ignore[arg-type]
        result = backend.compose(PlanRequest(goal="extract keywords", candidates=[]))
        assert result.status == "success"
        assert backend.last_decomposition is None

    def test_decomposition_enabled_with_flag(self) -> None:
        """When use_decomposition=True, decomposition is attempted."""
        call_count = 0
        decomp_json = json.dumps({
            "content_transforms": ["extract_keywords"],
            "presentation": "none",
            "final_output_names": ["keywords"],
        })
        ir_json = json.dumps({
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "extract", "skill_id": "text.extract_keywords.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"keywords": {"step": "extract", "port": "keywords"}},
            "effects": ["llm_inference"],
        })

        class TwoCallProvider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return decomp_json
                return ir_json

        backend = IRPlannerBackend(
            TwoCallProvider(), candidate_count=1, use_decomposition=True,  # type: ignore[arg-type]
        )
        result = backend.compose(PlanRequest(goal="extract keywords", candidates=[]))
        assert result.status == "success"
        assert backend.last_decomposition is not None
        assert backend.last_decomposition.content_transforms == ["extract_keywords"]

    def test_decomposition_fallback_on_parse_error(self) -> None:
        """Bad decomposition JSON falls back to deterministic decomposition."""
        call_count = 0
        ir_json = json.dumps({
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "extract", "skill_id": "text.extract_keywords.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"keywords": {"step": "extract", "port": "keywords"}},
            "effects": ["llm_inference"],
        })

        class BadDecompProvider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return "not json at all"
                return ir_json

        backend = IRPlannerBackend(
            BadDecompProvider(), candidate_count=1, use_decomposition=True,  # type: ignore[arg-type]
        )
        result = backend.compose(PlanRequest(goal="extract keywords", candidates=[]))
        assert result.status == "success"
        # Fallback decomposition should still be set
        assert backend.last_decomposition is not None
        assert "extract_keywords" in backend.last_decomposition.content_transforms

    def test_reranked_with_decomposition(self) -> None:
        """Decomposition + reranking: scorer uses decomposition for consistency."""
        decomp_json = json.dumps({
            "content_transforms": ["extract_keywords"],
            "presentation": "none",
            "final_output_names": ["keywords"],
        })
        good_ir = json.dumps({
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "extract", "skill_id": "text.extract_keywords.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"keywords": {"step": "extract", "port": "keywords"}},
            "effects": ["llm_inference"],
        })
        bad_ir = json.dumps({
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "extract", "skill_id": "text.extract_keywords.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}},
                {"name": "format", "skill_id": "text.join_lines.v1",
                 "sources": {"lines": {"step": "extract", "port": "keywords"}}}
            ],
            "final_outputs": {"joined": {"step": "format", "port": "joined"}},
            "effects": ["llm_inference"],
        })

        call_count = 0

        class MixedProvider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                nonlocal call_count
                call_count += 1
                if call_count == 1:  # decomposition call
                    return decomp_json
                if call_count == 2:  # first IR candidate (bad)
                    return bad_ir
                return good_ir  # second and third (good)

        backend = IRPlannerBackend(
            MixedProvider(), candidate_count=3, use_decomposition=True,  # type: ignore[arg-type]
        )
        result = backend.compose(PlanRequest(goal="extract keywords", candidates=[]))
        assert result.status == "success"
        assert result.graph is not None
        # The good candidate (no formatting) should win due to decomposition consistency
        assert "keywords" in result.graph.graph.outputs
        assert len(result.graph.graph.nodes) == 1


# ── No regression on existing reranking ────────────────────────────


class TestNoRegression:
    def test_reranking_without_decomposition_unchanged(self) -> None:
        good_ir = json.dumps({
            "inputs": [{"name": "text"}],
            "steps": [
                {"name": "extract", "skill_id": "text.extract_keywords.v1",
                 "sources": {"text": {"step": "input", "port": "text"}}}
            ],
            "final_outputs": {"keywords": {"step": "extract", "port": "keywords"}},
            "effects": ["llm_inference"],
        })

        class FixedProvider:
            def generate(self, prompt: str, **kwargs: object) -> str:
                return good_ir

        backend = IRPlannerBackend(FixedProvider(), candidate_count=3)  # type: ignore[arg-type]
        result = backend.compose(PlanRequest(goal="extract keywords", candidates=[]))
        assert result.status == "success"
        assert backend.last_decomposition is None
