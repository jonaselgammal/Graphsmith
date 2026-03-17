"""Skill package YAML loader."""
from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

from graphsmith.exceptions import ParseError
from graphsmith.models import ExamplesFile, GraphBody, SkillMetadata, SkillPackage


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file into a dictionary."""
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        raise ParseError(f"Failed to parse YAML file: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ParseError(f"Expected YAML mapping at top level in {path}")
    return data


def load_skill_package(path: str | Path) -> SkillPackage:
    """Load a skill package directory into internal models."""
    root = Path(path)
    if not root.exists():
        raise ParseError(f"Package path does not exist: {root}")
    if not root.is_dir():
        raise ParseError(f"Package path must be a directory: {root}")

    required = ["skill.yaml", "graph.yaml", "examples.yaml"]
    missing = [name for name in required if not (root / name).exists()]
    if missing:
        raise ParseError(f"Missing required files: {', '.join(missing)}")

    skill = SkillMetadata.model_validate(_read_yaml(root / "skill.yaml"))
    graph = GraphBody.model_validate(_read_yaml(root / "graph.yaml"))
    examples = ExamplesFile.model_validate(_read_yaml(root / "examples.yaml"))

    return SkillPackage(root_path=str(root), skill=skill, graph=graph, examples=examples)
