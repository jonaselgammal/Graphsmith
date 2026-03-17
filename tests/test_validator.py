"""Tests for the deterministic validator."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from graphsmith.exceptions import ValidationError
from graphsmith.parser import load_skill_package
from graphsmith.validator import validate_skill_package

from conftest import minimal_examples, minimal_graph, minimal_skill, write_package


# ── helpers ──────────────────────────────────────────────────────────


def _make_pkg(tmp_path: Path, *, skill=None, graph=None, examples=None):
    """Build and return a loaded SkillPackage from dict overrides."""
    write_package(
        tmp_path,
        skill=skill or minimal_skill(),
        graph=graph or minimal_graph(),
        examples=examples or minimal_examples(),
    )
    return load_skill_package(tmp_path)


# ── valid packages ───────────────────────────────────────────────────


def test_validate_summarize(summarize_path: Path) -> None:
    pkg = load_skill_package(summarize_path)
    validate_skill_package(pkg)


def test_validate_literature(literature_path: Path) -> None:
    pkg = load_skill_package(literature_path)
    validate_skill_package(pkg)


def test_validate_minimal(tmp_path: Path) -> None:
    pkg = _make_pkg(tmp_path / "pkg")
    validate_skill_package(pkg)


# ── duplicate node IDs ───────────────────────────────────────────────


def test_duplicate_node_ids(tmp_path: Path) -> None:
    graph = minimal_graph()
    graph["nodes"].append(
        {"id": "step", "op": "template.render", "config": {"template": "dup"}}
    )
    pkg = _make_pkg(tmp_path / "pkg", graph=graph)
    with pytest.raises(ValidationError, match="Duplicate node IDs"):
        validate_skill_package(pkg)


# ── reserved node IDs ───────────────────────────────────────────────


def test_reserved_node_id_input(tmp_path: Path) -> None:
    graph = minimal_graph()
    graph["nodes"][0]["id"] = "input"
    graph["edges"][0]["to"] = "input.text"
    graph["outputs"]["result"] = "input.rendered"
    pkg = _make_pkg(tmp_path / "pkg", graph=graph)
    with pytest.raises(ValidationError, match="Reserved node ID"):
        validate_skill_package(pkg)


# ── invalid ops ──────────────────────────────────────────────────────


def test_unknown_op(tmp_path: Path) -> None:
    graph = minimal_graph()
    graph["nodes"][0]["op"] = "magic.spell"
    pkg = _make_pkg(tmp_path / "pkg", graph=graph)
    with pytest.raises(ValidationError, match="Unknown op.*magic.spell"):
        validate_skill_package(pkg)


# ── invalid effects ──────────────────────────────────────────────────


def test_unknown_effect(tmp_path: Path) -> None:
    skill = minimal_skill()
    skill["effects"] = ["teleportation"]
    pkg = _make_pkg(tmp_path / "pkg", skill=skill)
    with pytest.raises(ValidationError, match="Unknown effect.*teleportation"):
        validate_skill_package(pkg)


# ── invalid types ────────────────────────────────────────────────────


def test_unknown_base_type(tmp_path: Path) -> None:
    skill = minimal_skill()
    skill["inputs"][0]["type"] = "float"
    pkg = _make_pkg(tmp_path / "pkg", skill=skill)
    with pytest.raises(ValidationError, match="Unknown type.*float"):
        validate_skill_package(pkg)


def test_valid_array_type(tmp_path: Path) -> None:
    skill = minimal_skill()
    skill["inputs"][0]["type"] = "array<string>"
    pkg = _make_pkg(tmp_path / "pkg", skill=skill)
    validate_skill_package(pkg)  # should not raise


def test_valid_optional_type(tmp_path: Path) -> None:
    skill = minimal_skill()
    skill["inputs"][0]["type"] = "optional<integer>"
    pkg = _make_pkg(tmp_path / "pkg", skill=skill)
    validate_skill_package(pkg)


def test_valid_nested_type(tmp_path: Path) -> None:
    skill = minimal_skill()
    skill["inputs"][0]["type"] = "array<optional<string>>"
    pkg = _make_pkg(tmp_path / "pkg", skill=skill)
    validate_skill_package(pkg)


def test_invalid_parameterised_type(tmp_path: Path) -> None:
    skill = minimal_skill()
    skill["inputs"][0]["type"] = "list<string>"
    pkg = _make_pkg(tmp_path / "pkg", skill=skill)
    with pytest.raises(ValidationError, match="Unknown parameterised type.*list"):
        validate_skill_package(pkg)


# ── edge references ──────────────────────────────────────────────────


def test_edge_unknown_source_node(tmp_path: Path) -> None:
    graph = minimal_graph()
    graph["edges"].append({"from": "ghost.out", "to": "step.extra"})
    pkg = _make_pkg(tmp_path / "pkg", graph=graph)
    with pytest.raises(ValidationError, match="unknown node.*ghost"):
        validate_skill_package(pkg)


def test_edge_unknown_dest_node(tmp_path: Path) -> None:
    graph = minimal_graph()
    graph["edges"][0]["to"] = "ghost.text"
    pkg = _make_pkg(tmp_path / "pkg", graph=graph)
    with pytest.raises(ValidationError, match="unknown node.*ghost"):
        validate_skill_package(pkg)


def test_edge_unknown_input_port(tmp_path: Path) -> None:
    graph = minimal_graph()
    graph["edges"][0] = {"from": "input.nonexistent", "to": "step.text"}
    pkg = _make_pkg(tmp_path / "pkg", graph=graph)
    with pytest.raises(ValidationError, match="undeclared input.*nonexistent"):
        validate_skill_package(pkg)


def test_malformed_address(tmp_path: Path) -> None:
    graph = minimal_graph()
    graph["edges"][0] = {"from": "no_dot", "to": "step.text"}
    pkg = _make_pkg(tmp_path / "pkg", graph=graph)
    with pytest.raises(ValidationError, match="Invalid address"):
        validate_skill_package(pkg)


# ── required inputs not wired ────────────────────────────────────────


def test_required_input_not_wired(tmp_path: Path) -> None:
    graph = minimal_graph()
    graph["edges"] = []  # remove all edges
    pkg = _make_pkg(tmp_path / "pkg", graph=graph)
    with pytest.raises(ValidationError, match="Required input.*not wired.*text"):
        validate_skill_package(pkg)


def test_optional_input_not_wired_ok(tmp_path: Path) -> None:
    skill = minimal_skill()
    skill["inputs"].append({"name": "hint", "type": "string", "required": False})
    pkg = _make_pkg(tmp_path / "pkg", skill=skill)
    validate_skill_package(pkg)  # should not raise


# ── output mappings ──────────────────────────────────────────────────


def test_missing_output_mapping(tmp_path: Path) -> None:
    skill = minimal_skill()
    skill["outputs"].append({"name": "extra", "type": "string"})
    pkg = _make_pkg(tmp_path / "pkg", skill=skill)
    with pytest.raises(ValidationError, match="missing from graph_outputs.*extra"):
        validate_skill_package(pkg)


def test_output_references_unknown_node(tmp_path: Path) -> None:
    graph = minimal_graph()
    graph["outputs"]["result"] = "phantom.rendered"
    pkg = _make_pkg(tmp_path / "pkg", graph=graph)
    with pytest.raises(ValidationError, match="unknown node.*phantom"):
        validate_skill_package(pkg)


def test_undeclared_graph_output(tmp_path: Path) -> None:
    graph = minimal_graph()
    graph["outputs"]["bonus"] = "step.rendered"
    pkg = _make_pkg(tmp_path / "pkg", graph=graph)
    with pytest.raises(ValidationError, match="not declared in skill.yaml"):
        validate_skill_package(pkg)


# ── DAG / cycle detection ───────────────────────────────────────────


def test_cycle_detected(tmp_path: Path) -> None:
    graph = {
        "version": 1,
        "nodes": [
            {"id": "a", "op": "template.render", "config": {"template": "{{x}}"}},
            {"id": "b", "op": "template.render", "config": {"template": "{{x}}"}},
        ],
        "edges": [
            {"from": "input.text", "to": "a.text"},
            {"from": "a.out", "to": "b.x"},
            {"from": "b.out", "to": "a.x"},
        ],
        "outputs": {"result": "b.rendered"},
    }
    pkg = _make_pkg(tmp_path / "pkg", graph=graph)
    with pytest.raises(ValidationError, match="cycle"):
        validate_skill_package(pkg)


def test_self_loop_detected(tmp_path: Path) -> None:
    graph = minimal_graph()
    graph["edges"].append({"from": "step.out", "to": "step.extra"})
    pkg = _make_pkg(tmp_path / "pkg", graph=graph)
    with pytest.raises(ValidationError, match="cycle"):
        validate_skill_package(pkg)
