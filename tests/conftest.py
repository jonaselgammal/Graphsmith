"""Shared test fixtures for Graphsmith."""
from __future__ import annotations

import json
import itertools
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest
import yaml

from graphsmith.registry import FileRemoteRegistry
from graphsmith.registry.api import (
    RemotePackageResponse,
    RemotePublishResponse,
    RemoteSearchResponse,
)
from graphsmith.registry.client import package_to_remote_files, remote_files_content_hash


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


@pytest.fixture()
def remote_registry_server(tmp_path: Path):
    """Build a mock HTTP remote registry backed by FileRemoteRegistry."""
    registry = FileRemoteRegistry(
        root=tmp_path / "remote-http-registry",
        registry_id="mock-http-remote",
        registry_url="http://testserver.invalid",
        owner="graphsmith-tests",
        trust_score=0.7,
    )
    publish_counter = itertools.count(1)

    def handler(request: httpx.Request) -> httpx.Response:
        parsed = urlparse(str(request.url))
        if request.method == "GET" and parsed.path == "/v1/manifest":
            return httpx.Response(200, json=registry.manifest.model_dump())

        if request.method == "GET" and parsed.path == "/v1/search":
            query = parse_qs(parsed.query)
            results = registry.search(
                query.get("q", [""])[0],
                effect=query.get("effect", [None])[0],
                tag=query.get("tag", [None])[0],
                input_name=query.get("input_name", [None])[0],
                output_name=query.get("output_name", [None])[0],
            )
            payload = RemoteSearchResponse(results=results, total_estimate=len(results))
            return httpx.Response(200, json=payload.model_dump())

        parts = [part for part in parsed.path.split("/") if part]
        if request.method == "GET" and len(parts) == 5 and parts[:2] == ["v1", "skills"] and parts[3] == "versions":
            skill_id = unquote(parts[2])
            version = unquote(parts[4])
            try:
                pkg = registry.fetch(skill_id, version)
            except Exception as exc:
                return httpx.Response(404, json={"error": str(exc)})
            entry = next(
                item for item in registry.list_all()
                if item.id == skill_id and item.version == version
            )
            files = package_to_remote_files(pkg.root_path)
            payload = RemotePackageResponse(
                manifest=registry.manifest,
                entry=entry,
                files=files,
                content_hash=remote_files_content_hash(files),
            )
            return httpx.Response(200, json=payload.model_dump())

        if request.method == "POST" and parsed.path == "/v1/skills":
            try:
                payload = json.loads(request.content.decode("utf-8"))
                files = payload["files"]
                pkg_root = tmp_path / "incoming" / f"pkg-{next(publish_counter)}"
                pkg_root.mkdir(parents=True, exist_ok=True)
                (pkg_root / "skill.yaml").write_text(files["skill_yaml"], encoding="utf-8")
                (pkg_root / "graph.yaml").write_text(files["graph_yaml"], encoding="utf-8")
                (pkg_root / "examples.yaml").write_text(files["examples_yaml"], encoding="utf-8")
                entry, warnings = registry.publish(pkg_root)
                response = RemotePublishResponse(
                    entry=entry,
                    warnings=warnings,
                    content_hash=remote_files_content_hash(package_to_remote_files(pkg_root)),
                )
                return httpx.Response(200, json=response.model_dump())
            except Exception as exc:
                return httpx.Response(400, json={"error": str(exc)})

        return httpx.Response(404, json={"error": f"Unknown route: {parsed.path}"})

    transport = httpx.MockTransport(handler)
    yield {
        "base_url": "https://mock-remote.test",
        "registry": registry,
        "transport": transport,
    }
