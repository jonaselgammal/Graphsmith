"""Shared test fixtures for Graphsmith."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "examples" / "skills"


@pytest.fixture()
def summarize_path() -> Path:
    return EXAMPLE_DIR / "text.summarize.v1"


@pytest.fixture()
def literature_path() -> Path:
    return EXAMPLE_DIR / "literature.quick_review.v1"


def write_package(
    root: Path,
    *,
    skill: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
    examples: dict[str, Any] | None = None,
) -> Path:
    """Write a minimal skill package to *root* and return the path.

    Any file whose value is ``None`` is skipped (useful for testing
    missing-file errors).
    """
    root.mkdir(parents=True, exist_ok=True)
    if skill is not None:
        (root / "skill.yaml").write_text(yaml.dump(skill), encoding="utf-8")
    if graph is not None:
        (root / "graph.yaml").write_text(yaml.dump(graph), encoding="utf-8")
    if examples is not None:
        (root / "examples.yaml").write_text(yaml.dump(examples), encoding="utf-8")
    return root


# ── Minimal valid package data ───────────────────────────────────────


def minimal_skill() -> dict[str, Any]:
    return {
        "id": "test.minimal.v1",
        "name": "Minimal Test",
        "version": "1.0.0",
        "description": "A minimal test skill.",
        "inputs": [{"name": "text", "type": "string", "required": True}],
        "outputs": [{"name": "result", "type": "string"}],
        "effects": ["pure"],
    }


def minimal_graph() -> dict[str, Any]:
    return {
        "version": 1,
        "nodes": [
            {"id": "step", "op": "template.render", "config": {"template": "{{text}}"}},
        ],
        "edges": [
            {"from": "input.text", "to": "step.text"},
        ],
        "outputs": {"result": "step.rendered"},
    }


def minimal_examples() -> dict[str, Any]:
    return {
        "examples": [
            {
                "name": "basic",
                "input": {"text": "hello"},
                "expected_output": {"result": "hello"},
            }
        ]
    }
