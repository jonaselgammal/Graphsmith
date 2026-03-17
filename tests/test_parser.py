"""Tests for the YAML package loader."""
from __future__ import annotations

from pathlib import Path

import pytest

from graphsmith.exceptions import ParseError
from graphsmith.models import SkillPackage
from graphsmith.parser import load_skill_package

from conftest import minimal_examples, minimal_graph, minimal_skill, write_package


# ── valid packages ───────────────────────────────────────────────────


def test_load_summarize(summarize_path: Path) -> None:
    pkg = load_skill_package(summarize_path)
    assert isinstance(pkg, SkillPackage)
    assert pkg.skill.id == "text.summarize.v1"
    assert pkg.skill.version == "1.0.0"
    assert len(pkg.graph.nodes) == 2
    assert len(pkg.graph.edges) == 2
    assert "summary" in pkg.graph.outputs
    assert len(pkg.examples.examples) == 1


def test_load_literature(literature_path: Path) -> None:
    pkg = load_skill_package(literature_path)
    assert pkg.skill.id == "literature.quick_review.v1"
    assert pkg.skill.effects == ["network_read", "llm_inference"]
    assert len(pkg.graph.nodes) == 3


def test_load_minimal_package(tmp_path: Path) -> None:
    write_package(
        tmp_path / "pkg",
        skill=minimal_skill(),
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    pkg = load_skill_package(tmp_path / "pkg")
    assert pkg.skill.id == "test.minimal.v1"


def test_skill_optional_fields(tmp_path: Path) -> None:
    skill = minimal_skill()
    skill["tags"] = ["demo"]
    skill["authors"] = ["tester"]
    skill["license"] = "MIT"
    write_package(
        tmp_path / "pkg",
        skill=skill,
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    pkg = load_skill_package(tmp_path / "pkg")
    assert pkg.skill.tags == ["demo"]
    assert pkg.skill.license == "MIT"


# ── missing files ────────────────────────────────────────────────────


def test_missing_skill_yaml(tmp_path: Path) -> None:
    write_package(
        tmp_path / "pkg",
        skill=None,
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    with pytest.raises(ParseError, match="Missing required files.*skill.yaml"):
        load_skill_package(tmp_path / "pkg")


def test_missing_graph_yaml(tmp_path: Path) -> None:
    write_package(
        tmp_path / "pkg",
        skill=minimal_skill(),
        graph=None,
        examples=minimal_examples(),
    )
    with pytest.raises(ParseError, match="Missing required files.*graph.yaml"):
        load_skill_package(tmp_path / "pkg")


def test_missing_examples_yaml(tmp_path: Path) -> None:
    write_package(
        tmp_path / "pkg",
        skill=minimal_skill(),
        graph=minimal_graph(),
        examples=None,
    )
    with pytest.raises(ParseError, match="Missing required files.*examples.yaml"):
        load_skill_package(tmp_path / "pkg")


# ── bad paths ────────────────────────────────────────────────────────


def test_nonexistent_path() -> None:
    with pytest.raises(ParseError, match="does not exist"):
        load_skill_package("/nonexistent/path")


def test_path_is_file(tmp_path: Path) -> None:
    f = tmp_path / "file.txt"
    f.write_text("hello")
    with pytest.raises(ParseError, match="must be a directory"):
        load_skill_package(f)


# ── malformed YAML ───────────────────────────────────────────────────


def test_invalid_yaml_syntax(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "skill.yaml").write_text("{{invalid yaml", encoding="utf-8")
    (pkg_dir / "graph.yaml").write_text("version: 1\nnodes: []\nedges: []\noutputs: {}", encoding="utf-8")
    (pkg_dir / "examples.yaml").write_text("examples: []", encoding="utf-8")
    with pytest.raises(ParseError, match="Failed to parse YAML"):
        load_skill_package(pkg_dir)


def test_yaml_not_a_mapping(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "skill.yaml").write_text("- a list\n- not a mapping", encoding="utf-8")
    (pkg_dir / "graph.yaml").write_text("version: 1\nnodes: []\nedges: []\noutputs: {}", encoding="utf-8")
    (pkg_dir / "examples.yaml").write_text("examples: []", encoding="utf-8")
    with pytest.raises(ParseError, match="Expected YAML mapping"):
        load_skill_package(pkg_dir)
