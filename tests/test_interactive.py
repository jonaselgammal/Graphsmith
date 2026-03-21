"""Tests for interactive CLI session formatting."""
from __future__ import annotations

from graphsmith.cli.interactive import (
    format_candidates,
    format_compare,
    format_plan_summary,
    HELP_TEXT,
)
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.planner.ir import IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.ir_backend import CandidateResult
from graphsmith.planner.ir_scorer import ScoreBreakdown
from graphsmith.planner.models import GlueGraph


def _make_glue(steps: list[tuple[str, str]], outputs: dict[str, str]) -> GlueGraph:
    nodes = [
        GraphNode(id=name, op="skill.invoke", config={"skill_id": skill})
        for name, skill in steps
    ]
    return GlueGraph(
        goal="test",
        inputs=[IOField(name="text", type="string")],
        outputs=[IOField(name=n, type="string") for n in outputs],
        effects=["llm_inference"],
        graph=GraphBody(
            version=1, nodes=nodes,
            edges=[GraphEdge(from_="input.text", to=f"{steps[0][0]}.text")] if steps else [],
            outputs=outputs,
        ),
    )


def _make_candidate(
    index: int, steps: list[tuple[str, str]], outputs: dict[str, str],
    score: float = 100.0, status: str = "compiled",
) -> CandidateResult:
    ir = PlanningIR(
        goal="test",
        inputs=[IRInput(name="text")],
        steps=[IRStep(name=n, skill_id=s, sources={"text": IRSource(step="input", port="text")})
               for n, s in steps],
        final_outputs={k: IROutputRef(step=k.split(".")[0] if "." in k else steps[-1][0], port=v.split(".")[-1])
                       for k, v in outputs.items()},
    )
    glue = _make_glue(steps, outputs) if status == "compiled" else None
    return CandidateResult(
        index=index, status=status, ir=ir, glue=glue,
        score=ScoreBreakdown(total=score, penalties=[], rewards=[]),
    )


class TestFormatPlanSummary:
    def test_single_step(self) -> None:
        glue = _make_glue(
            [("extract", "text.extract_keywords.v1")],
            {"keywords": "extract.keywords"},
        )
        text = format_plan_summary(glue)
        assert "Plan Summary" in text
        assert "extract" in text
        assert "keywords" in text
        assert "Steps:" in text
        assert "Outputs:" in text

    def test_multi_step(self) -> None:
        glue = _make_glue(
            [("normalize", "text.normalize.v1"), ("summarize", "text.summarize.v1")],
            {"summary": "summarize.summary"},
        )
        text = format_plan_summary(glue)
        assert "1. normalize" in text
        assert "2. summarize" in text

    def test_effects_shown(self) -> None:
        glue = _make_glue([("x", "text.normalize.v1")], {"n": "x.n"})
        text = format_plan_summary(glue)
        assert "llm_inference" in text


class TestFormatCandidates:
    def test_compiled_candidates(self) -> None:
        cands = [
            _make_candidate(0, [("extract", "text.extract_keywords.v1")],
                            {"keywords": "extract.keywords"}, score=115),
            _make_candidate(1, [("extract", "text.extract_keywords.v1"),
                                ("format", "text.join_lines.v1")],
                            {"joined": "format.joined"}, score=80),
        ]
        text = format_candidates(cands)
        assert "Candidate 1" in text
        assert "Candidate 2" in text
        assert "115" in text
        assert "80" in text
        assert "SELECTED" in text  # candidate 1 has higher score

    def test_failed_candidate(self) -> None:
        cands = [
            _make_candidate(0, [("x", "text.normalize.v1")], {"n": "x.n"}, score=100),
            CandidateResult(index=1, status="parse_error", error="bad json"),
        ]
        text = format_candidates(cands)
        assert "parse_error" in text
        assert "bad json" in text

    def test_empty_candidates(self) -> None:
        assert "No candidates" in format_candidates([])


class TestFormatCompare:
    def test_compare_two_candidates(self) -> None:
        cands = [
            _make_candidate(0, [("normalize", "text.normalize.v1"),
                                ("summarize", "text.summarize.v1")],
                            {"summary": "summarize.summary"}, score=120),
            _make_candidate(1, [("summarize", "text.summarize.v1")],
                            {"summary": "summarize.summary"}, score=95),
        ]
        text = format_compare(cands)
        assert "Selected" in text
        assert "Alternative" in text
        assert "Differences" in text
        assert "normalize" in text.lower()

    def test_compare_needs_two(self) -> None:
        cands = [_make_candidate(0, [("x", "text.normalize.v1")], {"n": "x.n"})]
        assert "Not enough" in format_compare(cands)


class TestHelpText:
    def test_help_contains_commands(self) -> None:
        assert ":help" in HELP_TEXT
        assert ":quit" in HELP_TEXT
        assert ":candidates" in HELP_TEXT
        assert ":compare" in HELP_TEXT
        assert ":rerun" in HELP_TEXT
        assert ":decomposition" in HELP_TEXT
