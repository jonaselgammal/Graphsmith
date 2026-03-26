"""File-backed mock remote registry.

This models the shape of a future shared remote skill repository without
requiring a network service yet.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from graphsmith.exceptions import ParseError, RegistryError, ValidationError
from graphsmith.models import SkillPackage
from graphsmith.parser import load_skill_package
from graphsmith.registry.index import IndexEntry, RemoteRegistryManifest
from graphsmith.validator import validate_skill_package


class FileRemoteRegistry:
    """Filesystem-backed mock remote registry with provenance-bearing entries."""

    def __init__(
        self,
        root: str | Path,
        *,
        registry_id: str | None = None,
        registry_url: str | None = None,
        display_name: str = "",
        owner: str = "",
        trust_score: float | None = 0.5,
    ) -> None:
        self._root = Path(root)
        self._skills_dir = self._root / "skills"
        self._index_path = self._root / "index.json"
        self._manifest_path = self._root / "manifest.json"
        if not self._manifest_path.exists():
            manifest = RemoteRegistryManifest(
                registry_id=registry_id or self._root.name or "remote-registry",
                display_name=display_name or registry_id or self._root.name,
                registry_url=registry_url or f"file://{self._root}",
                owner=owner,
                trust_score=trust_score,
            )
            self._save_manifest(manifest)

    @property
    def root(self) -> Path:
        return self._root

    @property
    def manifest(self) -> RemoteRegistryManifest:
        if not self._manifest_path.exists():
            raise RegistryError(f"Remote registry manifest not found: {self._manifest_path}")
        raw = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        return RemoteRegistryManifest.model_validate(raw)

    def publish(self, path: str | Path) -> tuple[IndexEntry, list[str]]:
        pkg = load_skill_package(path)
        validate_skill_package(pkg)
        manifest = self.manifest
        sid = pkg.skill.id
        ver = pkg.skill.version

        index = self._load_index()
        for entry in index:
            if entry.id == sid and entry.version == ver:
                raise RegistryError(f"Skill '{sid}' version '{ver}' is already published")

        dest = self._skills_dir / sid / ver
        dest.mkdir(parents=True, exist_ok=True)
        src = Path(pkg.root_path)
        for name in ("skill.yaml", "graph.yaml", "examples.yaml"):
            shutil.copy2(src / name, dest / name)

        entry = IndexEntry(
            id=sid,
            name=pkg.skill.name,
            version=ver,
            description=pkg.skill.description,
            tags=list(pkg.skill.tags),
            effects=list(pkg.skill.effects),
            input_names=[f.name for f in pkg.skill.inputs],
            required_input_names=[f.name for f in pkg.skill.inputs if f.required],
            optional_input_names=[f.name for f in pkg.skill.inputs if not f.required],
            output_names=[f.name for f in pkg.skill.outputs],
            published_at=datetime.now(timezone.utc).isoformat(),
            source_kind="remote",
            registry_id=manifest.registry_id,
            registry_url=manifest.registry_url,
            publisher=manifest.owner,
            trust_score=manifest.trust_score,
            manifest_version=manifest.manifest_version,
            remote_ref=f"{manifest.registry_id}:{sid}@{ver}",
        )
        index.append(entry)
        self._save_index(index)
        return entry, []

    def fetch(self, skill_id: str, version: str) -> SkillPackage:
        pkg_dir = self._skills_dir / skill_id / version
        if not pkg_dir.is_dir():
            raise RegistryError(f"Skill '{skill_id}' version '{version}' not found in remote registry")
        return load_skill_package(pkg_dir)

    def has(self, skill_id: str, version: str) -> bool:
        return (self._skills_dir / skill_id / version).is_dir()

    def search(
        self,
        query: str = "",
        *,
        effect: str | None = None,
        tag: str | None = None,
        input_name: str | None = None,
        output_name: str | None = None,
    ) -> list[IndexEntry]:
        index = self._load_index()
        results: list[IndexEntry] = []
        for entry in index:
            if query and not entry.matches_text(query):
                continue
            if not entry.matches_filters(
                effect=effect,
                tag=tag,
                input_name=input_name,
                output_name=output_name,
            ):
                continue
            results.append(entry)
        results.sort(key=lambda e: (e.id, e.version))
        return results

    def list_all(self) -> list[IndexEntry]:
        return self.search()

    def _load_index(self) -> list[IndexEntry]:
        if not self._index_path.exists():
            return []
        raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        return [IndexEntry.model_validate(e) for e in raw]

    def _save_index(self, entries: list[IndexEntry]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text(
            json.dumps([e.model_dump() for e in entries], indent=2) + "\n",
            encoding="utf-8",
        )

    def _save_manifest(self, manifest: RemoteRegistryManifest) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._manifest_path.write_text(
            json.dumps(manifest.model_dump(), indent=2) + "\n",
            encoding="utf-8",
        )
