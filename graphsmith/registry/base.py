"""Registry backend protocol and shared helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from graphsmith.models import SkillPackage
from graphsmith.registry.index import IndexEntry


class RegistryBackend(Protocol):
    """Common interface implemented by local, remote, and aggregate registries."""

    @property
    def root(self) -> Path: ...

    def publish(self, path: str | Path) -> tuple[IndexEntry, list[str]]: ...

    def fetch(self, skill_id: str, version: str) -> SkillPackage: ...

    def has(self, skill_id: str, version: str) -> bool: ...

    def search(
        self,
        query: str = "",
        *,
        effect: str | None = None,
        tag: str | None = None,
        input_name: str | None = None,
        output_name: str | None = None,
    ) -> list[IndexEntry]: ...

    def list_all(self) -> list[IndexEntry]: ...
