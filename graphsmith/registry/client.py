"""HTTP client for remote Graphsmith registries."""
from __future__ import annotations

import hashlib
import json
import tempfile
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
        cache_root: str | Path | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._auth_token = auth_token
        self._transport = transport
        self._cache_root = (
            Path(cache_root)
            if cache_root
            else Path(tempfile.gettempdir()) / "graphsmith-remote-cache"
        )

    @property
    def root(self) -> Path:
        return Path(self._base_url)

    @property
    def manifest(self) -> RemoteRegistryManifest:
        try:
            data = self._request_json("GET", "/v1/manifest")
            manifest = RemoteRegistryManifest.model_validate(data)
            self._save_json(self._cache_registry_dir() / "manifest.json", manifest.model_dump())
            return manifest
        except RegistryError:
            cached = self._load_json(self._cache_registry_dir() / "manifest.json")
            if cached is None:
                raise
            return RemoteRegistryManifest.model_validate(cached)

    def publish(self, path: str | Path) -> tuple[IndexEntry, list[str]]:
        files = package_to_remote_files(path)
        req = RemotePublishRequest(files=files)
        data = self._request_json("POST", "/v1/skills", json=req.model_dump())
        resp = RemotePublishResponse.model_validate(data)
        self._cache_package(resp.entry, files)
        self._refresh_cached_index(resp.entry)
        return resp.entry, resp.warnings

    def fetch(self, skill_id: str, version: str) -> SkillPackage:
        path = f"/v1/skills/{quote(skill_id, safe='')}/versions/{quote(version, safe='')}"
        try:
            data = self._request_json("GET", path)
            resp = RemotePackageResponse.model_validate(data)
            self._save_json(self._cache_registry_dir() / "manifest.json", resp.manifest.model_dump())
            self._cache_package(resp.entry, resp.files)
            return load_skill_package(self._package_cache_dir(skill_id, version))
        except RegistryError:
            cached = self._load_cached_package(skill_id, version)
            if cached is None:
                raise
            return cached

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
        cache_path = self._search_cache_path(params)
        try:
            data = self._request_json("GET", "/v1/search", params=params)
            resp = RemoteSearchResponse.model_validate(data)
            self._save_json(cache_path, resp.model_dump())
            if not query and not effect and not tag and not input_name and not output_name:
                self._save_json(
                    self._cache_registry_dir() / "index.json",
                    [entry.model_dump() for entry in resp.results],
                )
            return resp.results
        except RegistryError:
            cached = self._load_json(cache_path)
            if cached is not None:
                return RemoteSearchResponse.model_validate(cached).results
            if not query and not effect and not tag and not input_name and not output_name:
                cached_index = self._load_json(self._cache_registry_dir() / "index.json")
                if cached_index is not None:
                    return [IndexEntry.model_validate(entry) for entry in cached_index]
            raise

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

    def _cache_registry_dir(self) -> Path:
        key = hashlib.sha1(self._base_url.encode("utf-8")).hexdigest()[:16]
        return self._cache_root / key

    def _search_cache_path(self, params: dict[str, Any]) -> Path:
        encoded = json.dumps(params, sort_keys=True)
        key = hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:16]
        return self._cache_registry_dir() / "search" / f"{key}.json"

    def _package_cache_dir(self, skill_id: str, version: str) -> Path:
        safe_id = quote(skill_id, safe="")
        safe_version = quote(version, safe="")
        return self._cache_registry_dir() / "packages" / safe_id / safe_version

    def _cache_package(self, entry: IndexEntry, files: RemoteSkillFiles) -> None:
        package_dir = self._package_cache_dir(entry.id, entry.version)
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "skill.yaml").write_text(files.skill_yaml, encoding="utf-8")
        (package_dir / "graph.yaml").write_text(files.graph_yaml, encoding="utf-8")
        (package_dir / "examples.yaml").write_text(files.examples_yaml, encoding="utf-8")
        self._save_json(package_dir / "entry.json", entry.model_dump())

    def _load_cached_package(self, skill_id: str, version: str) -> SkillPackage | None:
        package_dir = self._package_cache_dir(skill_id, version)
        if not package_dir.is_dir():
            return None
        try:
            return load_skill_package(package_dir)
        except Exception:
            return None

    def _refresh_cached_index(self, entry: IndexEntry) -> None:
        index_path = self._cache_registry_dir() / "index.json"
        current = self._load_json(index_path) or []
        entries = [IndexEntry.model_validate(item) for item in current]
        merged: dict[tuple[str, str], IndexEntry] = {
            (item.id, item.version): item for item in entries
        }
        merged[(entry.id, entry.version)] = entry
        self._save_json(
            index_path,
            [item.model_dump() for item in sorted(merged.values(), key=lambda e: (e.id, e.version))],
        )

    def _load_json(self, path: Path) -> Any | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
