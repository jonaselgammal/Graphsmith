"""HTTP client for remote Graphsmith registries."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import yaml

from graphsmith.exceptions import RegistryError
from graphsmith.models import ExamplesFile, GraphBody, SkillMetadata, SkillPackage
from graphsmith.parser import load_skill_package
from graphsmith.registry.api import (
    RemotePackageResponse,
    RemotePublishRequest,
    RemotePublishResponse,
    RemoteSearchResponse,
    RemoteSkillFiles,
)
from graphsmith.registry.index import IndexEntry, RemoteRegistryManifest


def package_to_remote_files(path: str | Path) -> RemoteSkillFiles:
    """Load a local skill package directory into transportable file strings."""
    pkg = load_skill_package(path)
    root = Path(pkg.root_path)
    return RemoteSkillFiles(
        skill_yaml=(root / "skill.yaml").read_text(encoding="utf-8"),
        graph_yaml=(root / "graph.yaml").read_text(encoding="utf-8"),
        examples_yaml=(root / "examples.yaml").read_text(encoding="utf-8"),
    )


def remote_files_content_hash(files: RemoteSkillFiles) -> str:
    """Compute a stable content hash for remote file payloads."""
    payload = "\n---\n".join([files.skill_yaml, files.graph_yaml, files.examples_yaml])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def remote_files_to_skill_package(
    files: RemoteSkillFiles,
    *,
    root_hint: str = "",
) -> SkillPackage:
    """Convert serialized package files back into a SkillPackage model."""
    skill = SkillMetadata.model_validate(yaml.safe_load(files.skill_yaml) or {})
    graph = GraphBody.model_validate(yaml.safe_load(files.graph_yaml) or {})
    examples = ExamplesFile.model_validate(yaml.safe_load(files.examples_yaml) or {})
    return SkillPackage(
        root_path=root_hint or "<remote>",
        skill=skill,
        graph=graph,
        examples=examples,
    )


class RemoteRegistryClient:
    """HTTP-backed remote registry implementing the common registry interface."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 20.0,
        auth_token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._auth_token = auth_token
        self._transport = transport

    @property
    def root(self) -> Path:
        return Path(self._base_url)

    @property
    def manifest(self) -> RemoteRegistryManifest:
        data = self._request_json("GET", "/v1/manifest")
        return RemoteRegistryManifest.model_validate(data)

    def publish(self, path: str | Path) -> tuple[IndexEntry, list[str]]:
        files = package_to_remote_files(path)
        req = RemotePublishRequest(files=files)
        data = self._request_json("POST", "/v1/skills", json=req.model_dump())
        resp = RemotePublishResponse.model_validate(data)
        return resp.entry, resp.warnings

    def fetch(self, skill_id: str, version: str) -> SkillPackage:
        path = f"/v1/skills/{quote(skill_id, safe='')}/versions/{quote(version, safe='')}"
        data = self._request_json("GET", path)
        resp = RemotePackageResponse.model_validate(data)
        return remote_files_to_skill_package(
            resp.files,
            root_hint=f"{resp.manifest.registry_id}:{skill_id}@{version}",
        )

    def has(self, skill_id: str, version: str) -> bool:
        try:
            self.fetch(skill_id, version)
            return True
        except RegistryError:
            return False

    def search(
        self,
        query: str = "",
        *,
        effect: str | None = None,
        tag: str | None = None,
        input_name: str | None = None,
        output_name: str | None = None,
    ) -> list[IndexEntry]:
        params: dict[str, Any] = {"q": query}
        if effect:
            params["effect"] = effect
        if tag:
            params["tag"] = tag
        if input_name:
            params["input_name"] = input_name
        if output_name:
            params["output_name"] = output_name
        data = self._request_json("GET", "/v1/search", params=params)
        resp = RemoteSearchResponse.model_validate(data)
        return resp.results

    def list_all(self) -> list[IndexEntry]:
        return self.search("")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        return headers

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            client_kwargs: dict[str, Any] = {
                "timeout": self._timeout_seconds,
                "headers": self._headers(),
            }
            if self._transport is not None:
                client_kwargs["transport"] = self._transport
            with httpx.Client(**client_kwargs) as client:
                resp = client.request(
                    method,
                    f"{self._base_url}{path}",
                    params=params,
                    json=json,
                )
        except Exception as exc:
            raise RegistryError(f"Remote registry request failed: {exc}") from exc
        if resp.status_code >= 400:
            detail = ""
            try:
                payload = resp.json()
                detail = payload.get("error", "")
            except Exception:
                detail = resp.text
            raise RegistryError(
                f"Remote registry request failed ({resp.status_code}): {detail or 'unknown error'}"
            )
        try:
            return resp.json()
        except Exception as exc:
            raise RegistryError(f"Remote registry returned invalid JSON: {exc}") from exc
