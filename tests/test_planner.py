"""Tests for the planner: candidates, backend, composer, validation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.planner import (
    GlueGraph,
    MockPlannerBackend,
    PlanRequest,
    PlanResult,
    UnresolvedHole,
    compose_plan,
    retrieve_candidates,
)
from graphsmith.planner.backend import PlannerBackend
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.planner.prompt import build_planning_context
from graphsmith.registry import LocalRegistry
from graphsmith.registry.index import IndexEntry
from graphsmith.validator import validate_skill_package

from conftest import EXAMPLE_DIR, minimal_examples, minimal_graph, minimal_skill, write_package


@pytest.fixture()
def reg(tmp_path: Path) -> LocalRegistry:
    return LocalRegistry(root=tmp_path / "registry")


@pytest.fixture()
def reg_with_skills(reg: LocalRegistry) -> LocalRegistry:
    """Registry with both example skills published."""
    reg.publish(EXAMPLE_DIR / "text.summarize.v1")
    reg.publish(EXAMPLE_DIR / "literature.quick_review.v1")
    return reg


# ── candidate retrieval ──────────────────────────────────────────────


class TestCandidateRetrieval:
    def test_retrieves_matching_skills(
        self, reg_with_skills: LocalRegistry
    ) -> None:
        candidates = retrieve_candidates("summarize text", reg_with_skills)
        ids = [c.id for c in candidates]
        assert "text.summarize.v1" in ids

    def test_retrieves_multiple(
        self, reg_with_skills: LocalRegistry
    ) -> None:
        candidates = retrieve_candidates(
            "summarize papers review", reg_with_skills
        )
        ids = [c.id for c in candidates]
        assert "text.summarize.v1" in ids
        assert "literature.quick_review.v1" in ids

    def test_no_match_returns_all(
        self, reg_with_skills: LocalRegistry
    ) -> None:
        candidates = retrieve_candidates(
            "xyzzy zork", reg_with_skills
        )
        # Falls back to listing all skills
        assert len(candidates) == 2

    def test_empty_registry(self, reg: LocalRegistry) -> None:
        candidates = retrieve_candidates("summarize text", reg)
        assert candidates == []

    def test_max_candidates(
        self, reg_with_skills: LocalRegistry
    ) -> None:
        candidates = retrieve_candidates(
            "summarize text", reg_with_skills, max_candidates=1
        )
        assert len(candidates) <= 1

    def test_deterministic_order(
        self, reg_with_skills: LocalRegistry
    ) -> None:
        a = retrieve_candidates("text review", reg_with_skills)
        b = retrieve_candidates("text review", reg_with_skills)
        assert [c.id for c in a] == [c.id for c in b]


# ── mock backend ─────────────────────────────────────────────────────


class TestMockBackend:
    def test_success_with_candidates(self) -> None:
        entry = IndexEntry(
            id="test.skill.v1",
            name="Test",
            version="1.0.0",
            description="A test skill.",
            input_names=["text"],
            output_names=["result"],
            effects=["pure"],
        )
        request = PlanRequest(goal="do something", candidates=[entry])
        backend = MockPlannerBackend()
        result = backend.compose(request)

        assert result.status == "success"
        assert result.graph is not None
        assert result.graph.goal == "do something"
        assert len(result.graph.graph.nodes) == 1
        assert result.graph.graph.nodes[0].op == "skill.invoke"
        assert result.holes == []

    def test_failure_with_no_candidates(self) -> None:
        request = PlanRequest(goal="do something", candidates=[])
        backend = MockPlannerBackend()
        result = backend.compose(request)

        assert result.status == "failure"
        assert result.graph is None
        assert len(result.holes) == 1
        assert result.holes[0].kind == "missing_skill"

    def test_partial_with_desired_outputs(self) -> None:
        entry = IndexEntry(
            id="test.skill.v1",
            name="Test",
            version="1.0.0",
            description="A test skill.",
            input_names=["text"],
            output_names=["result"],
            effects=["pure"],
        )
        request = PlanRequest(
            goal="do something",
            candidates=[entry],
            desired_outputs=[
                IOField(name="result", type="string"),
                IOField(name="extra", type="string"),
            ],
        )
        backend = MockPlannerBackend()
        result = backend.compose(request)

        assert result.status == "partial"
        assert result.graph is not None
        assert len(result.holes) == 1
        assert result.holes[0].kind == "missing_output_path"
        assert "extra" in result.holes[0].description


# ── prompt builder ───────────────────────────────────────────────────


class TestPromptBuilder:
    def test_includes_goal(self) -> None:
        request = PlanRequest(
            goal="summarize some text",
            candidates=[],
        )
        ctx = build_planning_context(request)
        assert "summarize some text" in ctx

    def test_includes_candidates(self) -> None:
        entry = IndexEntry(
            id="text.summarize.v1",
            name="Summarize",
            version="1.0.0",
            description="Summarizes.",
            input_names=["text"],
            output_names=["summary"],
        )
        request = PlanRequest(
            goal="summarize",
            candidates=[entry],
        )
        ctx = build_planning_context(request)
        assert "text.summarize.v1@1.0.0" in ctx
        assert "text" in ctx
        assert "summary" in ctx

    def test_includes_constraints(self) -> None:
        request = PlanRequest(
            goal="test",
            candidates=[],
            constraints=["no network"],
        )
        ctx = build_planning_context(request)
        assert "no network" in ctx


# ── composer (end-to-end) ────────────────────────────────────────────


class TestComposer:
    def test_compose_success(
        self, reg_with_skills: LocalRegistry
    ) -> None:
        result = compose_plan(
            "summarize text",
            reg_with_skills,
            MockPlannerBackend(),
        )
        assert result.status == "success"
        assert result.graph is not None
        assert len(result.candidates_considered) > 0
        assert result.retrieval is not None
        assert result.retrieval.goal == "summarize text"

    def test_compose_empty_registry(self, reg: LocalRegistry) -> None:
        result = compose_plan(
            "summarize text",
            reg,
            MockPlannerBackend(),
        )
        assert result.status == "failure"
        assert result.graph is None
        assert result.retrieval is not None

    def test_compose_validates_graph(
        self, reg_with_skills: LocalRegistry
    ) -> None:
        """The composed graph should pass validation."""
        result = compose_plan(
            "summarize text",
            reg_with_skills,
            MockPlannerBackend(),
        )
        assert result.status == "success"
        assert result.graph is not None
        pkg = glue_to_skill_package(result.graph)
        validate_skill_package(pkg)  # should not raise

    def test_compose_with_max_candidates(
        self, reg_with_skills: LocalRegistry
    ) -> None:
        result = compose_plan(
            "summarize text",
            reg_with_skills,
            MockPlannerBackend(),
            max_candidates=1,
        )
        assert len(result.candidates_considered) <= 1


# ── validation of invalid glue graphs ────────────────────────────────


class TestGlueValidation:
    def test_invalid_graph_demoted_to_partial(self) -> None:
        """A backend returning a bad graph gets demoted."""

        class BadBackend:
            def compose(self, request: PlanRequest) -> PlanResult:
                # Create a graph with an unknown op
                glue = GlueGraph(
                    goal=request.goal,
                    inputs=[IOField(name="x", type="string")],
                    outputs=[IOField(name="y", type="string")],
                    effects=["pure"],
                    graph=GraphBody(
                        version=1,
                        nodes=[
                            GraphNode(id="bad", op="magic.spell", config={})
                        ],
                        edges=[GraphEdge(from_="input.x", to="bad.x")],
                        outputs={"y": "bad.out"},
                    ),
                )
                return PlanResult(
                    status="success",
                    graph=glue,
                    reasoning="Bad plan.",
                )

        reg = LocalRegistry(root="/tmp/empty_reg_test")
        result = compose_plan("test", reg, BadBackend())
        assert result.status == "partial"
        assert any(h.kind == "validation_error" for h in result.holes)

    def test_glue_to_skill_package(self) -> None:
        glue = GlueGraph(
            goal="test",
            inputs=[IOField(name="text", type="string")],
            outputs=[IOField(name="result", type="string")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(
                        id="step",
                        op="template.render",
                        config={"template": "{{text}}"},
                    )
                ],
                edges=[GraphEdge(from_="input.text", to="step.text")],
                outputs={"result": "step.rendered"},
            ),
        )
        pkg = glue_to_skill_package(glue)
        assert pkg.skill.id.startswith("_glue.")
        assert pkg.skill.version == "0.0.0"
        validate_skill_package(pkg)  # should not raise


# ── unresolved hole model ────────────────────────────────────────────


class TestUnresolvedHole:
    def test_hole_fields(self) -> None:
        hole = UnresolvedHole(
            node_id="step1",
            kind="missing_skill",
            description="No skill for PDF parsing.",
            candidates=["pdf.parse.v1"],
        )
        assert hole.node_id == "step1"
        assert hole.kind == "missing_skill"
        assert "PDF" in hole.description

    def test_hole_serialization(self) -> None:
        hole = UnresolvedHole(
            node_id="x",
            kind="ambiguous_candidate",
            description="Multiple matches.",
        )
        d = hole.model_dump()
        assert d["kind"] == "ambiguous_candidate"
        assert d["candidates"] == []
