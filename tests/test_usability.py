"""Tests for usability features: doctor, run, plan summary."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from graphsmith.cli.main import _summarize_plan, app

runner = CliRunner()


class TestDoctor:
    def test_doctor_runs_without_crash(self) -> None:
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "Graphsmith Doctor" in result.output

    def test_doctor_checks_python(self) -> None:
        result = runner.invoke(app, ["doctor"])
        assert "Python" in result.output

    def test_doctor_checks_deps(self) -> None:
        result = runner.invoke(app, ["doctor"])
        assert "pydantic" in result.output
        assert "typer" in result.output

    def test_doctor_checks_skills(self) -> None:
        result = runner.invoke(app, ["doctor"])
        assert "skills" in result.output.lower()


class TestPlanSummary:
    def test_summarize_plan_formatting(self) -> None:
        from graphsmith.models.common import IOField
        from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
        from graphsmith.planner.models import GlueGraph

        glue = GlueGraph(
            goal="test",
            inputs=[IOField(name="text", type="string")],
            outputs=[IOField(name="keywords", type="string")],
            effects=["llm_inference"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(id="extract", op="skill.invoke",
                              config={"skill_id": "text.extract_keywords.v1"}),
                ],
                edges=[GraphEdge(from_="input.text", to="extract.text")],
                outputs={"keywords": "extract.keywords"},
            ),
        )
        summary = _summarize_plan(glue)
        assert "Steps:" in summary
        assert "extract" in summary
        assert "keywords" in summary
        assert "Outputs:" in summary

    def test_summarize_multi_step(self) -> None:
        from graphsmith.models.common import IOField
        from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
        from graphsmith.planner.models import GlueGraph

        glue = GlueGraph(
            goal="test",
            inputs=[IOField(name="text", type="string")],
            outputs=[IOField(name="summary", type="string")],
            effects=["llm_inference"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(id="normalize", op="skill.invoke",
                              config={"skill_id": "text.normalize.v1"}),
                    GraphNode(id="summarize", op="skill.invoke",
                              config={"skill_id": "text.summarize.v1"}),
                ],
                edges=[
                    GraphEdge(from_="input.text", to="normalize.text"),
                    GraphEdge(from_="normalize.normalized", to="summarize.text"),
                ],
                outputs={"summary": "summarize.summary"},
            ),
        )
        summary = _summarize_plan(glue)
        assert "1. normalize" in summary
        assert "2. summarize" in summary


class TestInstallScript:
    def test_install_script_exists(self) -> None:
        path = Path(__file__).resolve().parents[1] / "scripts" / "install.sh"
        assert path.is_file()
        assert path.stat().st_mode & 0o100  # executable

    def test_env_example_exists(self) -> None:
        path = Path(__file__).resolve().parents[1] / ".env.example"
        assert path.is_file()
        content = path.read_text()
        assert "GRAPHSMITH_ANTHROPIC_API_KEY" in content


class TestVersionFlag:
    def test_version_flag(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "1.0.0" in result.output
