"""Tests for the local registry."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from graphsmith.exceptions import ParseError, RegistryError, ValidationError
from graphsmith.registry import LocalRegistry

from conftest import (
    EXAMPLE_DIR,
    minimal_examples,
    minimal_graph,
    minimal_skill,
    write_package,
)


@pytest.fixture()
def reg(tmp_path: Path) -> LocalRegistry:
    """A fresh registry in a tmp dir."""
    return LocalRegistry(root=tmp_path / "registry")


# ── publish ──────────────────────────────────────────────────────────


class TestPublish:
    def test_publish_valid_skill(self, reg: LocalRegistry) -> None:
        entry, _ = reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        assert entry.id == "text.summarize.v1"
        assert entry.version == "1.0.0"
        assert "llm_inference" in entry.effects
        assert "text" in entry.input_names
        assert "summary" in entry.output_names
        assert entry.published_at  # non-empty

    def test_publish_creates_files(self, reg: LocalRegistry) -> None:
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        pkg_dir = reg.root / "skills" / "text.summarize.v1" / "1.0.0"
        assert (pkg_dir / "skill.yaml").exists()
        assert (pkg_dir / "graph.yaml").exists()
        assert (pkg_dir / "examples.yaml").exists()

    def test_publish_creates_index(self, reg: LocalRegistry) -> None:
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        index_path = reg.root / "index.json"
        assert index_path.exists()

    def test_publish_duplicate_fails(self, reg: LocalRegistry) -> None:
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        with pytest.raises(RegistryError, match="already published"):
            reg.publish(EXAMPLE_DIR / "text.summarize.v1")

    def test_publish_invalid_skill_fails(
        self, reg: LocalRegistry, tmp_path: Path
    ) -> None:
        skill = minimal_skill()
        skill["effects"] = ["teleportation"]
        write_package(
            tmp_path / "bad_pkg",
            skill=skill,
            graph=minimal_graph(),
            examples=minimal_examples(),
        )
        with pytest.raises(ValidationError):
            reg.publish(tmp_path / "bad_pkg")

    def test_publish_nonexistent_path_fails(self, reg: LocalRegistry) -> None:
        with pytest.raises(ParseError):
            reg.publish("/nonexistent")

    def test_publish_multiple_skills(self, reg: LocalRegistry) -> None:
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        reg.publish(EXAMPLE_DIR / "literature.quick_review.v1")
        entries = reg.list_all()
        assert len(entries) == 2

    def test_publish_custom_package(
        self, reg: LocalRegistry, tmp_path: Path
    ) -> None:
        write_package(
            tmp_path / "pkg",
            skill=minimal_skill(),
            graph=minimal_graph(),
            examples=minimal_examples(),
        )
        entry, _ = reg.publish(tmp_path / "pkg")
        assert entry.id == "test.minimal.v1"


# ── fetch ────────────────────────────────────────────────────────────


class TestFetch:
    def test_fetch_published_skill(self, reg: LocalRegistry) -> None:
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        pkg = reg.fetch("text.summarize.v1", "1.0.0")
        assert pkg.skill.id == "text.summarize.v1"
        assert len(pkg.graph.nodes) == 2

    def test_fetch_not_found(self, reg: LocalRegistry) -> None:
        with pytest.raises(RegistryError, match="not found"):
            reg.fetch("nonexistent.v1", "1.0.0")

    def test_fetch_wrong_version(self, reg: LocalRegistry) -> None:
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        with pytest.raises(RegistryError, match="not found"):
            reg.fetch("text.summarize.v1", "9.9.9")

    def test_has_published(self, reg: LocalRegistry) -> None:
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        assert reg.has("text.summarize.v1", "1.0.0")
        assert not reg.has("text.summarize.v1", "2.0.0")
        assert not reg.has("nonexistent", "1.0.0")

    def test_fetch_deterministic(self, reg: LocalRegistry) -> None:
        """Fetching the same skill twice returns equal packages."""
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        a = reg.fetch("text.summarize.v1", "1.0.0")
        b = reg.fetch("text.summarize.v1", "1.0.0")
        assert a.skill.id == b.skill.id
        assert a.skill.version == b.skill.version
        assert len(a.graph.nodes) == len(b.graph.nodes)


# ── search ───────────────────────────────────────────────────────────


class TestSearch:
    @pytest.fixture(autouse=True)
    def _publish_examples(self, reg: LocalRegistry) -> None:
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        reg.publish(EXAMPLE_DIR / "literature.quick_review.v1")

    def test_search_text_id(self, reg: LocalRegistry) -> None:
        results = reg.search("summarize")
        ids = [r.id for r in results]
        assert "text.summarize.v1" in ids

    def test_search_text_tag(self, reg: LocalRegistry) -> None:
        results = reg.search("text")
        assert any(r.id == "text.summarize.v1" for r in results)

    def test_search_text_description(self, reg: LocalRegistry) -> None:
        results = reg.search("papers")
        assert any(r.id == "literature.quick_review.v1" for r in results)

    def test_search_empty_returns_all(self, reg: LocalRegistry) -> None:
        results = reg.search("")
        assert len(results) == 2

    def test_search_no_match(self, reg: LocalRegistry) -> None:
        results = reg.search("zzzznonexistent")
        assert results == []

    def test_search_filter_effect(self, reg: LocalRegistry) -> None:
        results = reg.search("", effect="network_read")
        assert len(results) == 1
        assert results[0].id == "literature.quick_review.v1"

    def test_search_filter_tag(self, reg: LocalRegistry) -> None:
        results = reg.search("", tag="summarization")
        assert len(results) == 1
        assert results[0].id == "text.summarize.v1"

    def test_search_filter_input(self, reg: LocalRegistry) -> None:
        results = reg.search("", input_name="query")
        assert len(results) == 1
        assert results[0].id == "literature.quick_review.v1"

    def test_search_filter_output(self, reg: LocalRegistry) -> None:
        results = reg.search("", output_name="summary")
        assert len(results) == 1
        assert results[0].id == "text.summarize.v1"

    def test_search_combined_text_and_filter(
        self, reg: LocalRegistry
    ) -> None:
        results = reg.search("text", effect="llm_inference")
        assert len(results) == 1
        assert results[0].id == "text.summarize.v1"

    def test_search_deterministic_order(self, reg: LocalRegistry) -> None:
        a = reg.search("")
        b = reg.search("")
        assert [e.id for e in a] == [e.id for e in b]
