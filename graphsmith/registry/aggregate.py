"""Aggregate local and remote registries behind one interface."""
from __future__ import annotations

from pathlib import Path

from graphsmith.exceptions import RegistryError
from graphsmith.models import SkillPackage
from graphsmith.registry.base import RegistryBackend
from graphsmith.registry.index import IndexEntry


class AggregatedRegistry:
    """Merge a preferred local registry with zero or more remote registries."""

    def __init__(
        self,
        local: RegistryBackend,
        remotes: list[RegistryBackend] | None = None,
    ) -> None:
        self._local = local
        self._remotes = remotes or []

    @property
    def root(self) -> Path:
        return self._local.root

    def publish(self, path: str | Path) -> tuple[IndexEntry, list[str]]:
        return self._local.publish(path)

    def fetch(self, skill_id: str, version: str) -> SkillPackage:
        for registry in [self._local, *self._remotes]:
            if registry.has(skill_id, version):
                return registry.fetch(skill_id, version)
        raise RegistryError(f"Skill '{skill_id}' version '{version}' not found in aggregated registry")

    def has(self, skill_id: str, version: str) -> bool:
        return any(registry.has(skill_id, version) for registry in [self._local, *self._remotes])

    def search(
        self,
        query: str = "",
        *,
        effect: str | None = None,
        tag: str | None = None,
        input_name: str | None = None,
        output_name: str | None = None,
    ) -> list[IndexEntry]:
        merged: dict[tuple[str, str], IndexEntry] = {}
        for registry in [self._local, *self._remotes]:
            for entry in registry.search(
                query,
                effect=effect,
                tag=tag,
                input_name=input_name,
                output_name=output_name,
            ):
                key = (entry.id, entry.version)
                if key not in merged:
                    merged[key] = entry
        return sorted(merged.values(), key=lambda e: (e.id, e.version))

    def list_all(self) -> list[IndexEntry]:
        return self.search()
