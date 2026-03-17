"""Tests for Pydantic models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from graphsmith.models import (
    ExampleCase,
    ExamplesFile,
    GraphBody,
    GraphEdge,
    GraphNode,
    IOField,
    QualityInfo,
    SkillMetadata,
    SkillPackage,
)


# ── IOField ──────────────────────────────────────────────────────────


def test_iofield_defaults() -> None:
    f = IOField(name="x", type="string")
    assert f.required is True
    assert f.description is None


def test_iofield_optional() -> None:
    f = IOField(name="x", type="integer", required=False, description="count")
    assert f.required is False
    assert f.description == "count"


# ── GraphEdge alias ──────────────────────────────────────────────────


def test_graph_edge_alias() -> None:
    edge = GraphEdge.model_validate({"from": "input.x", "to": "step.y"})
    assert edge.from_ == "input.x"
    assert edge.to == "step.y"


def test_graph_edge_by_field_name() -> None:
    edge = GraphEdge(from_="input.x", to="step.y")
    assert edge.from_ == "input.x"


# ── GraphNode ────────────────────────────────────────────────────────


def test_graph_node_minimal() -> None:
    node = GraphNode(id="a", op="template.render")
    assert node.inputs == {}
    assert node.config == {}
    assert node.when is None


# ── GraphBody ────────────────────────────────────────────────────────


def test_graph_body_round_trip() -> None:
    body = GraphBody(
        version=1,
        nodes=[GraphNode(id="a", op="template.render")],
        edges=[GraphEdge(from_="input.x", to="a.text")],
        outputs={"result": "a.rendered"},
    )
    assert len(body.nodes) == 1
    assert body.outputs["result"] == "a.rendered"


# ── SkillMetadata ────────────────────────────────────────────────────


def test_skill_metadata_required_fields() -> None:
    with pytest.raises(PydanticValidationError):
        SkillMetadata(id="x")  # type: ignore[call-arg]


def test_skill_metadata_defaults() -> None:
    sm = SkillMetadata(
        id="x",
        name="X",
        version="1.0.0",
        description="desc",
        inputs=[],
        outputs=[],
        effects=["pure"],
    )
    assert sm.tags == []
    assert sm.dependencies == []
    assert sm.quality is None


# ── QualityInfo ──────────────────────────────────────────────────────


def test_quality_info() -> None:
    q = QualityInfo(latency_ms_p50=120, success_rate=0.98)
    assert q.latency_ms_p50 == 120


# ── ExampleCase ──────────────────────────────────────────────────────


def test_example_case_no_expected() -> None:
    ec = ExampleCase(name="test", input={"a": 1})
    assert ec.expected_output is None


# ── ExamplesFile ─────────────────────────────────────────────────────


def test_examples_file_empty() -> None:
    ef = ExamplesFile()
    assert ef.examples == []


# ── JSON Schema export ───────────────────────────────────────────────


def test_skill_json_schema() -> None:
    schema = SkillMetadata.model_json_schema()
    assert "properties" in schema
    assert "id" in schema["properties"]


def test_graph_json_schema() -> None:
    schema = GraphBody.model_json_schema()
    assert "properties" in schema
