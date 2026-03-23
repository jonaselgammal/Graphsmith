"""Tests for UI backend state layer."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.planner.ir_backend import CandidateResult, IRPlannerBackend
from graphsmith.planner.models import GlueGraph, PlanResult
from graphsmith.ui.server import UIState, _compute_dict_diff, _glue_to_dict


def _make_glue(goal: str = "test", steps: list[tuple[str, str]] | None = None,
               outputs: dict[str, str] | None = None) -> GlueGraph:
    steps = steps or [("normalize", "text.normalize.v1")]
    outputs = outputs or {"normalized": "normalize.normalized"}
    return GlueGraph(
        goal=goal,
        inputs=[IOField(name="text", type="string")],
        outputs=[IOField(name=n, type="string") for n in outputs],
        effects=["pure"],
        graph=GraphBody(
            version=1,
            nodes=[GraphNode(id=name, op="skill.invoke", config={"skill_id": skill})
                   for name, skill in steps],
            edges=[GraphEdge(from_="input.text", to=f"{steps[0][0]}.text")],
            outputs=outputs,
        ),
    )


class _MockBackend:
    """Simulates IRPlannerBackend for testing."""

    def __init__(self, plan: GlueGraph | None = None) -> None:
        self._plan = plan or _make_glue()
        self._candidate_count = 3
        self._use_decomposition = True
        self._last_candidates: list[CandidateResult] = []
        self._last_decomposition = None

    @property
    def last_candidates(self) -> list[CandidateResult]:
        return self._last_candidates

    @property
    def last_decomposition(self):
        return self._last_decomposition

    def compose(self, request):
        self._last_candidates = []
        return PlanResult(status="success", graph=self._plan)


class TestGlueToDict:
    def test_has_graph_structure(self) -> None:
        glue = _make_glue()
        d = _glue_to_dict(glue)
        assert d["goal"] == "test"
        assert len(d["graph"]["nodes"]) == 1
        assert d["graph"]["nodes"][0]["id"] == "normalize"
        assert "normalized" in d["graph"]["outputs"]

    def test_has_inputs_outputs(self) -> None:
        d = _glue_to_dict(_make_glue())
        assert d["inputs"][0]["name"] == "text"
        assert d["outputs"][0]["name"] == "normalized"


class TestComputeDictDiff:
    def test_added_step(self) -> None:
        before = _glue_to_dict(_make_glue(steps=[("a", "s1")], outputs={"x": "a.x"}))
        after = _glue_to_dict(_make_glue(steps=[("a", "s1"), ("b", "s2")], outputs={"x": "a.x"}))
        diff = _compute_dict_diff(before, after)
        assert "b" in diff["added_steps"]

    def test_removed_step(self) -> None:
        before = _glue_to_dict(_make_glue(steps=[("a", "s1"), ("b", "s2")], outputs={"x": "a.x"}))
        after = _glue_to_dict(_make_glue(steps=[("a", "s1")], outputs={"x": "a.x"}))
        diff = _compute_dict_diff(before, after)
        assert "b" in diff["removed_steps"]

    def test_added_output(self) -> None:
        before = _glue_to_dict(_make_glue(outputs={"x": "a.x"}))
        after = _glue_to_dict(_make_glue(outputs={"x": "a.x", "y": "b.y"}))
        diff = _compute_dict_diff(before, after)
        assert "y" in diff["added_outputs"]


class TestUIState:
    def _make_state(self, plan: GlueGraph | None = None) -> UIState:
        from graphsmith.registry.local import LocalRegistry
        import tempfile
        reg = LocalRegistry(tempfile.mkdtemp())
        return UIState(_MockBackend(plan), reg)

    def test_plan_success(self) -> None:
        state = self._make_state()
        result = state.plan("test goal")
        assert result["status"] == "success"
        assert "graph" in result
        assert result["version"] == 1

    def test_plan_records_version(self) -> None:
        state = self._make_state()
        state.plan("goal 1")
        state.plan("goal 2")
        assert len(state.plan_versions) == 2

    def test_get_versions(self) -> None:
        state = self._make_state()
        state.plan("goal 1")
        state.plan("goal 2")
        versions = state.get_versions()
        assert len(versions) == 2
        assert versions[0]["index"] == 1

    def test_get_version(self) -> None:
        state = self._make_state()
        state.plan("my goal")
        v = state.get_version(1)
        assert v is not None
        assert "graph" in v

    def test_get_diff(self) -> None:
        glue1 = _make_glue(steps=[("a", "s1")], outputs={"x": "a.x"})
        glue2 = _make_glue(steps=[("a", "s1"), ("b", "s2")], outputs={"x": "a.x"})

        class TwoPlans:
            _candidate_count = 1
            _use_decomposition = False
            _last_candidates = []
            _last_decomposition = None
            _call = 0
            last_candidates = []
            last_decomposition = None

            def compose(self, request):
                self._call += 1
                g = glue1 if self._call == 1 else glue2
                return PlanResult(status="success", graph=g)

        import tempfile
        from graphsmith.registry.local import LocalRegistry
        state = UIState(TwoPlans(), LocalRegistry(tempfile.mkdtemp()))
        state.plan("v1")
        state.plan("v2")
        diff = state.get_diff()
        assert "b" in diff["added_steps"]

    def test_refine(self) -> None:
        state = self._make_state()
        state.plan("normalize and extract")
        result = state.refine("also keep the normalized text")
        assert result["status"] == "success"
        assert len(state.plan_versions) == 2
