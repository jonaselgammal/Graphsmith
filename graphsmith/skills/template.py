"""Skill scaffold generator."""
from __future__ import annotations

from pathlib import Path


def create_skill_template(name: str, output_dir: str | Path = ".") -> Path:
    """Generate a minimal skill scaffold directory.

    Args:
        name: Skill ID (e.g. 'text.uppercase.v1')
        output_dir: Parent directory for the new skill folder

    Returns:
        Path to the created skill directory
    """
    skill_dir = Path(output_dir) / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Derive defaults from name
    parts = name.replace(".v1", "").replace(".v2", "").split(".")
    op_name = ".".join(parts)  # e.g. "text.uppercase"
    short_name = parts[-1] if parts else name
    human_name = short_name.replace("_", " ").title()

    # skill.yaml
    (skill_dir / "skill.yaml").write_text(f"""\
id: {name}
name: {human_name}
version: 1.0.0
description: TODO — describe what this skill does.

inputs:
  - name: text
    type: string
    required: true

outputs:
  - name: result
    type: string

effects:
  - pure

tags:
  - {parts[0] if parts else 'custom'}
""")

    # graph.yaml
    (skill_dir / "graph.yaml").write_text(f"""\
version: 1

nodes:
  - id: run
    op: {op_name}

edges:
  - from: input.text
    to: run.text

outputs:
  result: run.result
""")

    # examples.yaml
    (skill_dir / "examples.yaml").write_text(f"""\
examples:
  - name: basic
    input:
      text: "hello world"
    expected_output:
      result: "TODO"
""")

    return skill_dir
