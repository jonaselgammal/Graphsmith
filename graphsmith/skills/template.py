"""Compatibility skill template scaffolding."""
from __future__ import annotations

from pathlib import Path


def create_skill_template(skill_id: str, output_dir: str | Path) -> Path:
    """Create a minimal editable skill package scaffold.

    This is intentionally small and exists as a compatibility helper for tests
    and manual bootstrapping.
    """
    skill_dir = Path(output_dir) / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    (skill_dir / "skill.yaml").write_text(
        "\n".join([
            f"id: {skill_id}",
            f"name: {skill_id}",
            "version: 1.0.0",
            "description: TODO",
            "",
            "inputs:",
            "  - name: text",
            "    type: string",
            "    required: true",
            "",
            "outputs:",
            "  - name: result",
            "    type: string",
            "",
            "effects:",
            "  - pure",
            "",
        ]),
        encoding="utf-8",
    )
    (skill_dir / "graph.yaml").write_text(
        "\n".join([
            "version: 1",
            "",
            "nodes:",
            "  - id: run",
            "    op: template.render",
            "    config:",
            "      template: \"{{text}}\"",
            "",
            "edges:",
            "  - from: input.text",
            "    to: run.text",
            "",
            "outputs:",
            "  result: run.rendered",
            "",
        ]),
        encoding="utf-8",
    )
    (skill_dir / "examples.yaml").write_text(
        "\n".join([
            "examples:",
            "  - name: example_1",
            "    input:",
            "      text: hello",
            "    expected_output:",
            "      result: hello",
            "",
        ]),
        encoding="utf-8",
    )
    return skill_dir
