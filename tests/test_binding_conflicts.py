"""Regression tests for conflicting bindings and skill output propagation (Sprint 10I).

Covers the real-world failure where a LLM-generated plan had two edges
targeting the same destination port.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphsmith.exceptions import ExecutionError, ValidationError
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.parser import load_skill_package
from graphsmith.planner import run_glue_graph
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.planner.models import GlueGraph
from graphsmith.planner.parser import parse_planner_output
from graphsmith.registry import LocalRegistry
from graphsmith.runtime import run_skill_package
from graphsmith.validator import validate_skill_package

from conftest import EXAMPLE_DIR, minimal_examples, minimal_graph, minimal_skill, write_package


# ── conflicting edge detection ───────────────────────────────────────


class TestConflictingBindings:
    def test_two_edges_same_dest_different_source(self, tmp_path: Path) -> None:
        """Two edges targeting the same port from different sources → validation error."""
        skill = minimal_skill()
        skill["inputs"].append({"name": "extra", "type": "string", "required": True})
        graph = {
            "version": 1,
            "nodes": [
                {"id": "step", "op": "template.render", "config": {"template": "{{text}}"}},
            ],
            "edges": [
                {"from": "input.text", "to": "step.text"},
                {"from": "input.extra", "to": "step.text"},  # conflict!
            ],
            "outputs": {"result": "step.rendered"},
        }
        write_package(tmp_path / "pkg", skill=skill, graph=graph, examples=minimal_examples())
        pkg = load_skill_package(tmp_path / "pkg")
        with pytest.raises(ValidationError, match="Conflicting edges"):
            validate_skill_package(pkg)

    def test_same_source_same_dest_is_ok(self, tmp_path: Path) -> None:
        """Duplicate identical edges are not conflicts."""
        graph = minimal_graph()
        # Add same edge again
        graph["edges"].append({"from": "input.text", "to": "step.text"})
        write_package(tmp_path / "pkg", skill=minimal_skill(), graph=graph, examples=minimal_examples())
        pkg = load_skill_package(tmp_path / "pkg")
        validate_skill_package(pkg)  # should not raise

    def test_single_edge_passes(self, tmp_path: Path) -> None:
        write_package(tmp_path / "pkg", skill=minimal_skill(), graph=minimal_graph(), examples=minimal_examples())
        pkg = load_skill_package(tmp_path / "pkg")
        validate_skill_package(pkg)  # should not raise

    def test_glue_graph_with_conflict_caught_by_validator(self) -> None:
        """A glue graph with conflicting bindings fails validation."""
        glue = GlueGraph(
            goal="test",
            inputs=[
                IOField(name="text", type="string"),
                IOField(name="alt", type="string"),
            ],
            outputs=[IOField(name="result", type="string")],
            effects=["pure"],
            graph=GraphBody(
                version=1,
                nodes=[GraphNode(id="s", op="template.render", config={"template": "{{text}}"})],
                edges=[
                    GraphEdge(from_="input.text", to="s.text"),
                    GraphEdge(from_="input.alt", to="s.text"),  # conflict
                ],
                outputs={"result": "s.rendered"},
            ),
        )
        pkg = glue_to_skill_package(glue)
        with pytest.raises(ValidationError, match="Conflicting edges"):
            validate_skill_package(pkg)

    def test_real_llm_plan_conflict(self) -> None:
        """The exact pattern from the saved LLM plan."""
        plan_json = json.dumps({
            "inputs": [{"name": "text", "type": "string"}],
            "outputs": [
                {"name": "normalized", "type": "string"},
                {"name": "keywords", "type": "string"},
            ],
            "nodes": [
                {"id": "normalize", "op": "skill.invoke",
                 "config": {"skill_id": "text.normalize.v1", "version": "1.0.0"}},
                {"id": "extract", "op": "skill.invoke",
                 "config": {"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}},
            ],
            "edges": [
                {"from": "input.text", "to": "normalize.text"},
                {"from": "input.text", "to": "extract.text"},
                {"from": "normalize.normalized", "to": "extract.text"},  # conflict
            ],
            "graph_outputs": {
                "normalized": "normalize.normalized",
                "keywords": "extract.keywords",
            },
            "effects": ["llm_inference"],
        })
        result = parse_planner_output(plan_json, goal="test")
        assert result.status == "success"  # parser doesn't check conflicts
        assert result.graph is not None

        # But validation catches the conflict
        from graphsmith.planner.composer import _validate_glue_graph
        validated = _validate_glue_graph(result)
        assert validated.status == "partial"
        assert any("Conflicting" in h.description for h in validated.holes)


# ── valid multi-skill plan (no conflict) ─────────────────────────────


class TestValidMultiSkillPlan:
    def test_chain_without_conflict(self, tmp_path: Path) -> None:
        """normalize → extract with proper serial wiring (no conflict)."""
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "text.normalize.v1")
        reg.publish(EXAMPLE_DIR / "text.extract_keywords.v1")

        glue = GlueGraph(
            goal="normalize and extract",
            inputs=[IOField(name="text", type="string")],
            outputs=[
                IOField(name="normalized", type="string"),
                IOField(name="keywords", type="string"),
            ],
            effects=["llm_inference"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(id="norm", op="skill.invoke",
                              config={"skill_id": "text.normalize.v1", "version": "1.0.0"}),
                    GraphNode(id="kw", op="skill.invoke",
                              config={"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}),
                ],
                edges=[
                    GraphEdge(from_="input.text", to="norm.text"),
                    GraphEdge(from_="norm.normalized", to="kw.text"),  # serial, not parallel
                ],
                outputs={
                    "normalized": "norm.normalized",
                    "keywords": "kw.keywords",
                },
            ),
        )

        # Validates
        pkg = glue_to_skill_package(glue)
        validate_skill_package(pkg)

        # Executes
        result = run_glue_graph(
            glue,
            {"text": "AI agents"},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=reg,
        )
        assert result.trace.status == "ok"
        assert "normalized" in result.outputs
        assert "keywords" in result.outputs


# ── skill output propagation ─────────────────────────────────────────


class TestSkillOutputPropagation:
    def test_extract_keywords_output_port(self) -> None:
        """text.extract_keywords.v1 outputs on port 'keywords'."""
        pkg = load_skill_package(EXAMPLE_DIR / "text.extract_keywords.v1")
        validate_skill_package(pkg)
        result = run_skill_package(
            pkg, {"text": "machine learning"},
            llm_provider=EchoLLMProvider(prefix=""),
        )
        assert "keywords" in result.outputs

    def test_normalize_output_port(self) -> None:
        """text.normalize.v1 outputs on port 'normalized'."""
        pkg = load_skill_package(EXAMPLE_DIR / "text.normalize.v1")
        validate_skill_package(pkg)
        result = run_skill_package(pkg, {"text": "Hello World"})
        assert "normalized" in result.outputs
