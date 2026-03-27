"""Remote registry API payload models."""
from __future__ import annotations

from pydantic import BaseModel, Field

from graphsmith.registry.index import IndexEntry, RemoteRegistryManifest


class RemoteSkillFiles(BaseModel):
    """Serialized package files for transport over the remote registry API."""

    skill_yaml: str
    graph_yaml: str
    examples_yaml: str


class RemotePublishRequest(BaseModel):
    """Request payload for publishing one immutable skill package."""

    manifest: RemoteRegistryManifest | None = None
    files: RemoteSkillFiles


class RemotePublishResponse(BaseModel):
    """Response payload after a successful remote publish."""

    entry: IndexEntry
    warnings: list[str] = Field(default_factory=list)
    content_hash: str = ""


class RemoteSearchResponse(BaseModel):
    """Search results returned by a remote registry."""

    results: list[IndexEntry] = Field(default_factory=list)
    next_cursor: str = ""
    total_estimate: int = 0


class RemotePackageResponse(BaseModel):
    """Fetch response containing full package contents and metadata."""

    manifest: RemoteRegistryManifest
    entry: IndexEntry
    files: RemoteSkillFiles
    content_hash: str = ""
