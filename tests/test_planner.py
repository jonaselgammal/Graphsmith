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
from graphsmith.planner.policy import derive_goal_constraints
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

    def test_filters_to_trusted_published_skills(self) -> None:
        class StubRegistry:
            root = Path("/tmp/stub")

            def list_all(self):
                return [
                    IndexEntry(
                        id="text.contains.v1",
                        name="Contains",
                        version="1.0.0",
                        description="Check whether text contains a phrase.",
                        tags=["text", "contains"],
                        input_names=["text", "phrase"],
                        output_names=["result"],
                        published_at="2026-03-27T00:00:00Z",
                        source_kind="remote",
                        trust_score=0.8,
                    ),
                    IndexEntry(
                        id="text.starts_with.v1",
                        name="Starts With",
                        version="1.0.0",
                        description="Check whether text starts with a prefix.",
                        tags=["text", "prefix"],
                        input_names=["text", "prefix"],
                        output_names=["result"],
                        published_at="2026-03-27T00:00:00Z",
                        source_kind="remote",
                        trust_score=0.4,
                    ),
                ]

            def search(self, query, **kwargs):
                return [e for e in self.list_all() if e.matches_text(query)]

        candidates = retrieve_candidates(
            "Using only trusted published skills, check whether text contains a phrase",
            StubRegistry(),
        )
        assert [c.id for c in candidates] == ["text.contains.v1"]

    def test_prefers_structurally_matching_synthesized_workflow(self, reg: LocalRegistry, tmp_path: Path) -> None:
        reg.publish(EXAMPLE_DIR / "text.prefix_lines.v1")
        workflow_dir = write_package(
            tmp_path / "workflow_pkg",
            skill={
                "id": "synth.file_transform_write_pytest_workflow.v1",
                "name": "Synth Workflow",
                "version": "1.0.0",
                "description": "read write pytest workflow",
                "inputs": [
                    {"name": "input_path", "type": "string", "required": True},
                    {"name": "output_path", "type": "string", "required": True},
                    {"name": "cwd", "type": "string", "required": True},
                ],
                "outputs": [{"name": "stdout", "type": "string"}],
                "effects": ["filesystem_read", "filesystem_write", "shell_exec", "pure"],
                "tags": [
                    "synthesized", "subgraph", "closed-loop", "validated",
                    "coding", "environment", "workflow:file_transform_write_pytest", "transform:title_case",
                ],
            },
            graph={
                "version": 1,
                "nodes": [{"id": "emit", "op": "template.render", "config": {"template": "{{cwd}}"}}],
                "edges": [
                    {"from": "input.input_path", "to": "emit.input_path"},
                    {"from": "input.output_path", "to": "emit.output_path"},
                    {"from": "input.cwd", "to": "emit.cwd"},
                ],
                "outputs": {"stdout": "emit.rendered"},
            },
            examples=minimal_examples(),
        )
        reg.publish(workflow_dir)

        candidates = retrieve_candidates(
            "Read a file, title case it, write it to a new file, run pytest in the project, and prefix each line of the test output",
            reg,
            max_candidates=3,
        )
        assert candidates[0].id == "synth.file_transform_write_pytest_workflow.v1"

    def test_prefers_smoke_tested_promoted_candidate(self, reg: LocalRegistry, tmp_path: Path) -> None:
        base_graph = {
            "version": 1,
            "nodes": [{"id": "fmt", "op": "template.render", "config": {"template": "{{text}}"}}],
            "edges": [{"from": "input.text", "to": "fmt.text"}],
            "outputs": {"summary": "fmt.rendered"},
        }
        plain_dir = write_package(
            tmp_path / "plain_pkg",
            skill={
                "id": "synth.summary_plain.v1",
                "name": "Summary Plain",
                "version": "1.0.0",
                "description": "plain summarized text workflow",
                "inputs": [{"name": "text", "type": "string", "required": True}],
                "outputs": [{"name": "summary", "type": "string"}],
                "effects": ["pure"],
                "tags": ["synthesized", "subgraph", "closed-loop", "validated", "transform:summarize"],
            },
            graph=base_graph,
            examples=minimal_examples(),
        )
        promoted_dir = write_package(
            tmp_path / "promoted_pkg",
            skill={
                "id": "synth.summary_promoted.v1",
                "name": "Summary Promoted",
                "version": "1.0.0",
                "description": "promoted summarized text workflow",
                "inputs": [{"name": "text", "type": "string", "required": True}],
                "outputs": [{"name": "summary", "type": "string"}],
                "effects": ["pure"],
                "tags": [
                    "synthesized", "subgraph", "closed-loop", "validated",
                    "smoke_tested", "promoted", "transform:summarize",
                ],
            },
            graph=base_graph,
            examples=minimal_examples(),
        )
        reg.publish(plain_dir)
        reg.publish(promoted_dir)

        candidates = retrieve_candidates("summarize this text", reg, max_candidates=2)
        assert candidates[0].id == "synth.summary_promoted.v1"


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

    def test_composes_reused_workflow_with_adjacent_formatter(self, reg: LocalRegistry, tmp_path: Path) -> None:
        workflow_dir = write_package(
            tmp_path / "workflow_pkg",
            skill={
                "id": "synth.file_transform_write_pytest_workflow.v1",
                "name": "Synth Workflow",
                "version": "1.0.0",
                "description": "read write pytest workflow",
                "inputs": [
                    {"name": "input_path", "type": "string", "required": True},
                    {"name": "output_path", "type": "string", "required": True},
                    {"name": "cwd", "type": "string", "required": True},
                ],
                "outputs": [{"name": "stdout", "type": "string"}],
                "effects": ["filesystem_read", "filesystem_write", "shell_exec", "pure"],
                "tags": [
                    "synthesized", "subgraph", "closed-loop", "validated",
                    "coding", "environment", "workflow:file_transform_write_pytest", "transform:title_case",
                ],
            },
            graph={
                "version": 1,
                "nodes": [{"id": "emit", "op": "template.render", "config": {"template": "{{cwd}}"}}],
                "edges": [
                    {"from": "input.input_path", "to": "emit.input_path"},
                    {"from": "input.output_path", "to": "emit.output_path"},
                    {"from": "input.cwd", "to": "emit.cwd"},
                ],
                "outputs": {"stdout": "emit.rendered"},
            },
            examples=minimal_examples(),
        )
        prefix_dir = write_package(
            tmp_path / "prefix_pkg",
            skill={
                "id": "text.prefix_lines.v1",
                "name": "Prefix Lines",
                "version": "1.0.0",
                "description": "Prefix each line.",
                "inputs": [
                    {"name": "text", "type": "string", "required": True},
                    {"name": "prefix", "type": "string", "required": True},
                ],
                "outputs": [{"name": "prefixed", "type": "string"}],
                "effects": ["pure"],
                "tags": ["text", "formatting"],
            },
            graph={
                "version": 1,
                "nodes": [{"id": "fmt", "op": "template.render", "config": {"template": "{{text}}"}}],
                "edges": [
                    {"from": "input.text", "to": "fmt.text"},
                    {"from": "input.prefix", "to": "fmt.prefix"},
                ],
                "outputs": {"prefixed": "fmt.rendered"},
            },
            examples=minimal_examples(),
        )
        reg.publish(workflow_dir)
        reg.publish(prefix_dir)

        request = PlanRequest(
            goal="Read a file, title case it, write it to a new file, run pytest in the project, and prefix each line of the test output",
            candidates=retrieve_candidates(
                "Read a file, title case it, write it to a new file, run pytest in the project, and prefix each line of the test output",
                reg,
            ),
        )
        result = MockPlannerBackend().compose(request)
        assert result.status == "success"
        assert result.graph is not None
        assert len(result.graph.graph.nodes) == 2
        ids = {node.config["skill_id"] for node in result.graph.graph.nodes if isinstance(node.config, dict)}
        assert "synth.file_transform_write_pytest_workflow.v1" in ids
        assert "text.prefix_lines.v1" in ids
        assert result.graph.graph.outputs == {"prefixed": "text_prefix_lines_v1.prefixed"}


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

    def test_derives_goal_policy_constraints(self) -> None:
        constraints = derive_goal_constraints(
            "Using only trusted published skills, check whether text contains a phrase",
        )
        assert constraints
        assert any("trusted published skills" in c for c in constraints)


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
