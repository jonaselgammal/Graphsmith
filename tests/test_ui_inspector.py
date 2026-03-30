"""Tests for Sprint 22: UI inspector and plan loading."""
from __future__ import annotations

from pathlib import Path

import pytest

from graphsmith.planner import load_plan
from graphsmith.planner.render import render_plan_mermaid, render_plan_text

PLANS_DIR = Path(__file__).resolve().parent.parent / "examples" / "plans"
UI_DIR = Path(__file__).resolve().parent.parent / "ui"
MANUAL_GOALS_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "manual_inspection_goals"


class TestUIFiles:
    def test_index_html_exists(self) -> None:
        assert (UI_DIR / "index.html").exists()

    def test_index_html_has_graphsmith(self) -> None:
        content = (UI_DIR / "index.html").read_text()
        assert "Graphsmith" in content

    def test_index_html_has_file_input(self) -> None:
        content = (UI_DIR / "index.html").read_text()
        assert 'type="file"' in content

    def test_index_html_has_svg(self) -> None:
        content = (UI_DIR / "index.html").read_text()
        assert "<svg" in content

    def test_index_html_has_drag_drop(self) -> None:
        content = (UI_DIR / "index.html").read_text()
        assert "dragover" in content
        assert "drop" in content

    def test_index_html_has_inspector_controls(self) -> None:
        content = (UI_DIR / "index.html").read_text()
        assert "Zoom In" in content
        assert "Zoom Out" in content
        assert "Hide Edge Labels" in content


class TestManualInspectionGoals:
    def test_manual_goal_exists(self) -> None:
        assert (MANUAL_GOALS_DIR / "hard_programming_probe.json").exists()

    def test_manual_goal_readme_exists(self) -> None:
        assert (MANUAL_GOALS_DIR / "README.md").exists()


class TestPlanLoadingForUI:
    def test_normalize_extract_loads(self) -> None:
        plan = load_plan(PLANS_DIR / "normalize_extract_keywords.json")
        assert plan.goal
        assert len(plan.graph.nodes) >= 2

    def test_three_skill_plan_loads(self) -> None:
        plan = load_plan(PLANS_DIR / "normalize_summarize_keywords.json")
        assert len(plan.graph.nodes) == 3

    def test_plan_has_graph_outputs(self) -> None:
        plan = load_plan(PLANS_DIR / "normalize_extract_keywords.json")
        assert len(plan.graph.outputs) >= 1

    def test_plan_edges_have_from_field(self) -> None:
        plan = load_plan(PLANS_DIR / "normalize_extract_keywords.json")
        for edge in plan.graph.edges:
            assert edge.from_  # from_ field populated

    def test_mermaid_export_works(self) -> None:
        plan = load_plan(PLANS_DIR / "normalize_extract_keywords.json")
        md = render_plan_mermaid(plan)
        assert "```mermaid" in md
        assert "normalize" in md

    def test_text_export_works(self) -> None:
        plan = load_plan(PLANS_DIR / "normalize_extract_keywords.json")
        text = render_plan_text(plan)
        assert "Plan:" in text
        assert "normalize" in text


class TestCLIUICommand:
    def test_ui_command_exists(self) -> None:
        from typer.testing import CliRunner
        from graphsmith.cli.main import app
        runner = CliRunner()
        result = runner.invoke(app, ["ui", "--help"])
        assert result.exit_code == 0
        assert "inspector" in result.output.lower() or "ui" in result.output.lower()
