"""Tests for plan deltas, refinement, and diff."""
from __future__ import annotations

from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.planner.deltas import (
    PlanDelta,
    PlanDiff,
    RefinementRequest,
    build_refined_goal,
    compute_diff,
    extract_deltas,
    format_diff,
)
from graphsmith.planner.models import GlueGraph


def _make_glue(steps: list[tuple[str, str]], outputs: dict[str, str]) -> GlueGraph:
    nodes = [
        GraphNode(id=name, op="skill.invoke", config={"skill_id": skill})
        for name, skill in steps
    ]
    return GlueGraph(
        goal="test", inputs=[IOField(name="text", type="string")],
        outputs=[IOField(name=n, type="string") for n in outputs],
        effects=[], graph=GraphBody(
            version=1, nodes=nodes,
            edges=[GraphEdge(from_="input.text", to=f"{steps[0][0]}.text")] if steps else [],
            outputs=outputs,
        ),
    )


# ── Delta extraction ─────────────────────────────────────────────


class TestExtractDeltas:
    def test_add_output(self) -> None:
        r = extract_deltas("also keep the normalized text")
        assert len(r.deltas) == 1
        assert r.deltas[0].kind == "add_output"
        assert r.deltas[0].target == "normalized"

    def test_also_output(self) -> None:
        r = extract_deltas("also output the keywords")
        assert r.deltas[0].kind == "add_output"
        assert r.deltas[0].target == "keywords"

    def test_forbid_skill(self) -> None:
        r = extract_deltas("don't summarize")
        assert len(r.deltas) == 1
        assert r.deltas[0].kind == "forbid_skill"
        assert "summarize" in r.deltas[0].target

    def test_skip_step(self) -> None:
        r = extract_deltas("skip the normalize step")
        assert r.deltas[0].kind == "forbid_skill"

    def test_add_step(self) -> None:
        r = extract_deltas("also uppercase the result")
        assert r.deltas[0].kind == "add_step"
        assert "uppercase" in r.deltas[0].target

    def test_replace_presentation(self) -> None:
        r = extract_deltas("replace the list with a header")
        assert r.deltas[0].kind == "replace_presentation"
        assert r.deltas[0].target == "header"

    def test_require_skill(self) -> None:
        r = extract_deltas("use text.normalize.v1")
        assert r.deltas[0].kind == "require_skill"
        assert r.deltas[0].target == "text.normalize.v1"

    def test_just_extract(self) -> None:
        r = extract_deltas("just extract keywords")
        assert r.deltas[0].kind == "require_skill"

    def test_fallback_to_goal_amendment(self) -> None:
        r = extract_deltas("something completely different and unmatched")
        assert len(r.deltas) == 0
        assert r.modified_goal != ""

    def test_do_not_remove(self) -> None:
        r = extract_deltas("do not summarize the text")
        assert r.deltas[0].kind == "forbid_skill"


# ── Goal building ────────────────────────────────────────────────


class TestBuildRefinedGoal:
    def test_add_output_goal(self) -> None:
        r = RefinementRequest(
            raw_request="keep normalized",
            deltas=[PlanDelta(kind="add_output", target="normalized")],
        )
        goal = build_refined_goal("extract keywords", r)
        assert "extract keywords" in goal
        assert "normalized" in goal

    def test_forbid_goal(self) -> None:
        r = RefinementRequest(
            raw_request="don't summarize",
            deltas=[PlanDelta(kind="forbid_skill", target="text.summarize.v1")],
        )
        goal = build_refined_goal("summarize and extract", r)
        assert "Do not summarize" in goal

    def test_fallback_amendment(self) -> None:
        r = RefinementRequest(
            raw_request="make it better",
            modified_goal="make it better",
        )
        goal = build_refined_goal("original goal", r)
        assert "original goal" in goal
        assert "make it better" in goal


# ── Plan diff ────────────────────────────────────────────────────


class TestComputeDiff:
    def test_added_step(self) -> None:
        before = _make_glue(
            [("normalize", "text.normalize.v1")],
            {"normalized": "normalize.normalized"},
        )
        after = _make_glue(
            [("normalize", "text.normalize.v1"), ("upper", "text.uppercase.v1")],
            {"uppercased": "upper.uppercased"},
        )
        diff = compute_diff(before, after)
        assert len(diff.added_steps) == 1
        assert "upper" in diff.added_steps[0]

    def test_removed_step(self) -> None:
        before = _make_glue(
            [("normalize", "text.normalize.v1"), ("summarize", "text.summarize.v1")],
            {"summary": "summarize.summary"},
        )
        after = _make_glue(
            [("normalize", "text.normalize.v1")],
            {"normalized": "normalize.normalized"},
        )
        diff = compute_diff(before, after)
        assert len(diff.removed_steps) == 1
        assert "summarize" in diff.removed_steps[0]

    def test_added_output(self) -> None:
        before = _make_glue(
            [("normalize", "text.normalize.v1")],
            {"keywords": "extract.keywords"},
        )
        after = _make_glue(
            [("normalize", "text.normalize.v1")],
            {"keywords": "extract.keywords", "normalized": "normalize.normalized"},
        )
        diff = compute_diff(before, after)
        assert "normalized" in diff.added_outputs

    def test_no_changes(self) -> None:
        plan = _make_glue(
            [("normalize", "text.normalize.v1")],
            {"normalized": "normalize.normalized"},
        )
        diff = compute_diff(plan, plan)
        assert not diff.added_steps
        assert not diff.removed_steps
        assert not diff.added_outputs


# ── Format diff ──────────────────────────────────────────────────


class TestFormatDiff:
    def test_shows_added(self) -> None:
        diff = PlanDiff(added_steps=["upper (text.uppercase.v1)"])
        text = format_diff(diff)
        assert "+ upper" in text

    def test_shows_removed(self) -> None:
        diff = PlanDiff(removed_steps=["summarize (text.summarize.v1)"])
        text = format_diff(diff)
        assert "- summarize" in text

    def test_no_changes(self) -> None:
        diff = PlanDiff()
        text = format_diff(diff)
        assert "no structural changes" in text
