"""Registry index entry model."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IndexEntry(BaseModel):
    """One entry in the registry index."""

    id: str
    name: str
    version: str
    description: str
    tags: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    input_names: list[str] = Field(default_factory=list)
    required_input_names: list[str] = Field(default_factory=list)
    optional_input_names: list[str] = Field(default_factory=list)
    output_names: list[str] = Field(default_factory=list)
    published_at: str = ""

    def matches_text(self, query: str) -> bool:
        """Case-insensitive substring match against searchable fields."""
        q = query.lower()
        if q in self.id.lower():
            return True
        if q in self.name.lower():
            return True
        if q in self.description.lower():
            return True
        for tag in self.tags:
            if q in tag.lower():
                return True
        return False

    def matches_filters(
        self,
        *,
        effect: str | None = None,
        tag: str | None = None,
        input_name: str | None = None,
        output_name: str | None = None,
    ) -> bool:
        """Return True if entry passes all provided filters (AND logic)."""
        if effect and effect not in self.effects:
            return False
        if tag and tag not in self.tags:
            return False
        if input_name and input_name not in self.input_names:
            return False
        if output_name and output_name not in self.output_names:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
