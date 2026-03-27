"""Local filesystem registry for Graphsmith skill packages."""
from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graphsmith.exceptions import ParseError, RegistryError, ValidationError
from graphsmith.models import SkillPackage
from graphsmith.parser import load_skill_package
from graphsmith.registry.index import IndexEntry
from graphsmith.validator import validate_skill_package

_DEFAULT_ROOT = Path.home() / ".graphsmith" / "registry"


class LocalRegistry:
    """Publish, fetch, and search skills in a local directory."""

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root) if root else _DEFAULT_ROOT
        self._skills_dir = self._root / "skills"
        self._index_path = self._root / "index.json"

    @property
    def root(self) -> Path:
        return self._root

    # ── publish ──────────────────────────────────────────────────────

    def publish(self, path: str | Path) -> tuple[IndexEntry, list[str]]:
        """Validate and publish a skill package into the registry.

        Returns (IndexEntry, warnings). Warnings are non-fatal messages
        such as missing declared dependencies.
        Raises RegistryError if (id, version) already exists.
        Raises ParseError / ValidationError on bad input.
        """
        pkg = load_skill_package(path)
        validate_skill_package(pkg)

        sid = pkg.skill.id
        ver = pkg.skill.version

        with self._publish_lock():
            # Check for duplicates
            index = self._load_index()
            for entry in index:
                if entry.id == sid and entry.version == ver:
                    raise RegistryError(
                        f"Skill '{sid}' version '{ver}' is already published"
                    )

            # Copy files
            dest = self._skills_dir / sid / ver
            dest.mkdir(parents=True, exist_ok=True)
            src = Path(pkg.root_path)
            for name in ("skill.yaml", "graph.yaml", "examples.yaml"):
                shutil.copy2(src / name, dest / name)

            # Build index entry
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
                source_kind="local",
                registry_id=str(self._root),
                registry_url=f"file://{self._root}",
                manifest_version="1",
            )
            index.append(entry)
            self._save_index(index)

        # Check dependencies (advisory only)
        warnings = self._check_dependencies(pkg, index)
        return entry, warnings

    def _check_dependencies(
        self, pkg: SkillPackage, index: list[IndexEntry],
    ) -> list[str]:
        """Warn about declared dependencies not in the registry."""
        published_ids = {e.id for e in index}
        # Also include primitive ops as valid dependencies
        from graphsmith.constants import PRIMITIVE_OPS
        known = published_ids | PRIMITIVE_OPS
        warnings: list[str] = []
        for dep in pkg.skill.dependencies:
            if dep not in known:
                warnings.append(
                    f"Dependency '{dep}' declared by '{pkg.skill.id}' "
                    f"is not in the registry"
                )
        return warnings

    # ── fetch ────────────────────────────────────────────────────────

    def fetch(self, skill_id: str, version: str) -> SkillPackage:
        """Load a published skill by exact (id, version).

        Raises RegistryError if not found.
        """
        pkg_dir = self._skills_dir / skill_id / version
        if not pkg_dir.is_dir():
            raise RegistryError(
                f"Skill '{skill_id}' version '{version}' not found in registry"
            )
        return load_skill_package(pkg_dir)

    def has(self, skill_id: str, version: str) -> bool:
        """Return True if (id, version) is published."""
        return (self._skills_dir / skill_id / version).is_dir()

    # ── search ───────────────────────────────────────────────────────

    def search(
        self,
        query: str = "",
        *,
        effect: str | None = None,
        tag: str | None = None,
        input_name: str | None = None,
        output_name: str | None = None,
    ) -> list[IndexEntry]:
        """Search the registry. Returns entries sorted by (id, version)."""
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
        """Return all published entries, sorted."""
        return self.search()

    # ── index I/O ────────────────────────────────────────────────────

    def _load_index(self) -> list[IndexEntry]:
        if not self._index_path.exists():
            return []
        raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        return [IndexEntry.model_validate(e) for e in raw]

    def _save_index(self, entries: list[IndexEntry]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        data = [e.model_dump() for e in entries]
        self._index_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    @contextmanager
    def _publish_lock(self) -> Any:
        """Serialize registry publishes across CLI processes."""
        self._root.mkdir(parents=True, exist_ok=True)
        lock_path = self._root / ".publish.lock"
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            try:
                import fcntl
            except ImportError:  # pragma: no cover - Windows fallback
                fcntl = None
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
