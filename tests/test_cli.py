"""Tests for the CLI commands."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from graphsmith.cli.main import app
from conftest import EXAMPLE_DIR, minimal_examples, minimal_graph, minimal_skill, write_package

runner = CliRunner()


# ── validate ─────────────────────────────────────────────────────────


def test_validate_succeeds() -> None:
    result = runner.invoke(app, ["validate", "examples/skills/text.summarize.v1"])
    assert result.exit_code == 0
    assert "OK" in result.output


def test_validate_bad_path() -> None:
    result = runner.invoke(app, ["validate", "/nonexistent"])
    assert result.exit_code == 1
    assert "FAIL" in result.output


def test_validate_invalid_package(tmp_path: Path) -> None:
    skill = minimal_skill()
    skill["effects"] = ["teleportation"]
    write_package(
        tmp_path / "pkg",
        skill=skill,
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    result = runner.invoke(app, ["validate", str(tmp_path / "pkg")])
    assert result.exit_code == 1
    assert "teleportation" in result.output


# ── inspect ──────────────────────────────────────────────────────────


def test_inspect_succeeds() -> None:
    result = runner.invoke(app, ["inspect", "examples/skills/text.summarize.v1"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == "text.summarize.v1"
    assert "inputs" in data
    assert "outputs" in data
    assert data["node_count"] == 2


def test_inspect_bad_path() -> None:
    result = runner.invoke(app, ["inspect", "/nonexistent"])
    assert result.exit_code == 1


# ── schema ───────────────────────────────────────────────────────────


def test_schema_skill() -> None:
    result = runner.invoke(app, ["schema", "skill"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "properties" in data


def test_schema_graph() -> None:
    result = runner.invoke(app, ["schema", "graph"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "properties" in data


def test_schema_examples() -> None:
    result = runner.invoke(app, ["schema", "examples"])
    assert result.exit_code == 0


def test_schema_unknown() -> None:
    result = runner.invoke(app, ["schema", "nope"])
    assert result.exit_code == 1


# ── run ──────────────────────────────────────────────────────────────


def test_run_minimal(tmp_path: Path) -> None:
    write_package(
        tmp_path / "pkg",
        skill=minimal_skill(),
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    result = runner.invoke(
        app,
        ["run", str(tmp_path / "pkg"), "--input", '{"text":"hello"}'],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {"result": "hello"}


def test_run_with_input_file(tmp_path: Path) -> None:
    write_package(
        tmp_path / "pkg",
        skill=minimal_skill(),
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    input_file = tmp_path / "input.json"
    input_file.write_text('{"text":"from file"}', encoding="utf-8")
    result = runner.invoke(
        app,
        ["run", str(tmp_path / "pkg"), "--input-file", str(input_file)],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {"result": "from file"}


def test_run_with_trace(tmp_path: Path) -> None:
    write_package(
        tmp_path / "pkg",
        skill=minimal_skill(),
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    result = runner.invoke(
        app,
        ["run", str(tmp_path / "pkg"), "--input", '{"text":"hi"}', "--trace"],
    )
    assert result.exit_code == 0
    assert "--- trace ---" in result.output


def test_run_bad_json_input() -> None:
    result = runner.invoke(
        app,
        ["run", "examples/skills/text.summarize.v1", "--input", "not json"],
    )
    assert result.exit_code == 1
    assert "Invalid JSON" in result.output


def test_run_no_llm_provider() -> None:
    """Summarize example needs an LLM provider — should fail cleanly."""
    result = runner.invoke(
        app,
        [
            "run",
            "examples/skills/text.summarize.v1",
            "--input",
            '{"text":"x","max_sentences":1}',
        ],
    )
    assert result.exit_code == 1
    assert "LLM provider" in result.output or "FAIL" in result.output


# ── publish ──────────────────────────────────────────────────────────


def test_publish_succeeds(tmp_path: Path) -> None:
    reg_root = tmp_path / "reg"
    result = runner.invoke(
        app,
        ["publish", str(EXAMPLE_DIR / "text.summarize.v1"), "--registry", str(reg_root)],
    )
    assert result.exit_code == 0
    assert "Published" in result.output
    assert "text.summarize.v1" in result.output


def test_publish_duplicate(tmp_path: Path) -> None:
    reg_root = tmp_path / "reg"
    runner.invoke(
        app,
        ["publish", str(EXAMPLE_DIR / "text.summarize.v1"), "--registry", str(reg_root)],
    )
    result = runner.invoke(
        app,
        ["publish", str(EXAMPLE_DIR / "text.summarize.v1"), "--registry", str(reg_root)],
    )
    assert result.exit_code == 1
    assert "already published" in result.output


def test_publish_bad_path(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["publish", "/nonexistent", "--registry", str(tmp_path / "reg")],
    )
    assert result.exit_code == 1


# ── search ───────────────────────────────────────────────────────────


def test_search_returns_results(tmp_path: Path) -> None:
    reg_root = tmp_path / "reg"
    runner.invoke(
        app,
        ["publish", str(EXAMPLE_DIR / "text.summarize.v1"), "--registry", str(reg_root)],
    )
    result = runner.invoke(
        app,
        ["search", "summarize", "--registry", str(reg_root)],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["id"] == "text.summarize.v1"


def test_search_no_results(tmp_path: Path) -> None:
    reg_root = tmp_path / "reg"
    result = runner.invoke(
        app,
        ["search", "nothing", "--registry", str(reg_root)],
    )
    assert result.exit_code == 0
    assert "No results" in result.output


def test_search_with_filter(tmp_path: Path) -> None:
    reg_root = tmp_path / "reg"
    runner.invoke(
        app,
        ["publish", str(EXAMPLE_DIR / "text.summarize.v1"), "--registry", str(reg_root)],
    )
    runner.invoke(
        app,
        ["publish", str(EXAMPLE_DIR / "literature.quick_review.v1"), "--registry", str(reg_root)],
    )
    result = runner.invoke(
        app,
        ["search", "", "--tag", "summarization", "--registry", str(reg_root)],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["id"] == "text.summarize.v1"


# ── show ─────────────────────────────────────────────────────────────


def test_show_published_skill(tmp_path: Path) -> None:
    reg_root = tmp_path / "reg"
    runner.invoke(
        app,
        ["publish", str(EXAMPLE_DIR / "text.summarize.v1"), "--registry", str(reg_root)],
    )
    result = runner.invoke(
        app,
        ["show", "text.summarize.v1", "--version", "1.0.0", "--registry", str(reg_root)],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == "text.summarize.v1"


def test_show_not_found(tmp_path: Path) -> None:
    reg_root = tmp_path / "reg"
    result = runner.invoke(
        app,
        ["show", "nonexistent", "--version", "1.0.0", "--registry", str(reg_root)],
    )
    assert result.exit_code == 1


# ── plan ─────────────────────────────────────────────────────────────


def test_plan_success(tmp_path: Path) -> None:
    reg_root = tmp_path / "reg"
    runner.invoke(
        app,
        ["publish", str(EXAMPLE_DIR / "text.summarize.v1"), "--registry", str(reg_root)],
    )
    result = runner.invoke(
        app,
        ["plan", "summarize text", "--registry", str(reg_root)],
    )
    assert result.exit_code == 0
    assert "Status: success" in result.output
    assert "skill.invoke" in result.output


def test_plan_json_output(tmp_path: Path) -> None:
    reg_root = tmp_path / "reg"
    runner.invoke(
        app,
        ["publish", str(EXAMPLE_DIR / "text.summarize.v1"), "--registry", str(reg_root)],
    )
    result = runner.invoke(
        app,
        ["plan", "summarize text", "--registry", str(reg_root), "--output-format", "json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["graph"] is not None


def test_plan_empty_registry(tmp_path: Path) -> None:
    reg_root = tmp_path / "reg"
    result = runner.invoke(
        app,
        ["plan", "do something", "--registry", str(reg_root)],
    )
    assert result.exit_code == 1
    assert "failure" in result.output.lower()


def test_plan_deterministic(tmp_path: Path) -> None:
    reg_root = tmp_path / "reg"
    runner.invoke(
        app,
        ["publish", str(EXAMPLE_DIR / "text.summarize.v1"), "--registry", str(reg_root)],
    )
    r1 = runner.invoke(
        app,
        ["plan", "summarize text", "--registry", str(reg_root), "--output-format", "json"],
    )
    r2 = runner.invoke(
        app,
        ["plan", "summarize text", "--registry", str(reg_root), "--output-format", "json"],
    )
    d1 = json.loads(r1.output)
    d2 = json.loads(r2.output)
    # Graph structure should be identical
    assert d1["graph"]["graph"] == d2["graph"]["graph"]


# ── run with trace persistence ───────────────────────────────────────


def test_run_persists_trace(tmp_path: Path) -> None:
    trace_root = tmp_path / "traces"
    write_package(
        tmp_path / "pkg",
        skill=minimal_skill(),
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    result = runner.invoke(
        app,
        [
            "run", str(tmp_path / "pkg"),
            "--input", '{"text":"hi"}',
            "--trace-root", str(trace_root),
        ],
    )
    assert result.exit_code == 0
    # Check trace was saved
    traces = list(trace_root.glob("*.json"))
    assert len(traces) == 1


# ── traces-list / traces-show ────────────────────────────────────────


def test_traces_list_empty(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["traces-list", "--trace-root", str(tmp_path / "traces")],
    )
    assert result.exit_code == 0
    assert "No traces" in result.output


def test_traces_list_and_show(tmp_path: Path) -> None:
    trace_root = tmp_path / "traces"
    write_package(
        tmp_path / "pkg",
        skill=minimal_skill(),
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    # Run to generate a trace
    runner.invoke(
        app,
        [
            "run", str(tmp_path / "pkg"),
            "--input", '{"text":"hi"}',
            "--trace-root", str(trace_root),
        ],
    )
    # List
    result = runner.invoke(app, ["traces-list", "--trace-root", str(trace_root)])
    assert result.exit_code == 0
    trace_id = result.output.strip()
    assert trace_id

    # Show
    result = runner.invoke(app, ["traces-show", trace_id, "--trace-root", str(trace_root)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["skill_id"] == "test.minimal.v1"


def test_traces_list_summary(tmp_path: Path) -> None:
    trace_root = tmp_path / "traces"
    write_package(
        tmp_path / "pkg",
        skill=minimal_skill(),
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    runner.invoke(
        app,
        [
            "run", str(tmp_path / "pkg"),
            "--input", '{"text":"hi"}',
            "--trace-root", str(trace_root),
        ],
    )
    result = runner.invoke(
        app,
        ["traces-list", "--trace-root", str(trace_root), "--summary"],
    )
    assert result.exit_code == 0
    assert "test.minimal.v1" in result.output
    assert "template.render" in result.output


def test_traces_show_not_found(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["traces-show", "nonexistent", "--trace-root", str(tmp_path / "traces")],
    )
    assert result.exit_code == 1


# ── promote-candidates ───────────────────────────────────────────────


def test_promote_candidates_empty(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["promote-candidates", "--trace-root", str(tmp_path / "traces")],
    )
    assert result.exit_code == 0
    assert "No promotion candidates" in result.output


def test_promote_candidates_with_data(tmp_path: Path) -> None:
    trace_root = tmp_path / "traces"
    write_package(
        tmp_path / "pkg",
        skill=minimal_skill(),
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    # Run 3 times to produce repeated traces
    for i in range(3):
        runner.invoke(
            app,
            [
                "run", str(tmp_path / "pkg"),
                "--input", f'{{"text":"run{i}"}}',
                "--trace-root", str(trace_root),
            ],
        )
    result = runner.invoke(
        app,
        ["promote-candidates", "--trace-root", str(trace_root), "--output-format", "json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) >= 1
    assert data[0]["signature"] == "template.render"
    assert data[0]["frequency"] >= 2
    assert data[0]["suggested_skill_id"].startswith("promoted.")


def test_promote_candidates_text_shows_example_traces(tmp_path: Path) -> None:
    trace_root = tmp_path / "traces"
    write_package(
        tmp_path / "pkg",
        skill=minimal_skill(),
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    for i in range(2):
        runner.invoke(
            app,
            [
                "run", str(tmp_path / "pkg"),
                "--input", f'{{"text":"run{i}"}}',
                "--trace-root", str(trace_root),
            ],
        )
    result = runner.invoke(
        app,
        ["promote-candidates", "--trace-root", str(trace_root)],
    )
    assert result.exit_code == 0
    assert "Suggested skill:" in result.output
    assert "Inspect examples:" in result.output
    assert "test.minimal.v1" in result.output


# ── traces-show --summary ────────────────────────────────────────────


def test_traces_show_summary(tmp_path: Path) -> None:
    trace_root = tmp_path / "traces"
    write_package(
        tmp_path / "pkg",
        skill=minimal_skill(),
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    runner.invoke(
        app,
        ["run", str(tmp_path / "pkg"), "--input", '{"text":"hi"}', "--trace-root", str(trace_root)],
    )
    # Get trace ID
    list_result = runner.invoke(app, ["traces-list", "--trace-root", str(trace_root)])
    tid = list_result.output.strip()

    result = runner.invoke(
        app,
        ["traces-show", tid, "--trace-root", str(trace_root), "--summary"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["node_count"] == 1
    assert data["op_signature"] == "template.render"


# ── traces-prune ─────────────────────────────────────────────────────


def test_traces_prune_nothing(tmp_path: Path) -> None:
    trace_root = tmp_path / "traces"
    write_package(
        tmp_path / "pkg",
        skill=minimal_skill(),
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    runner.invoke(
        app,
        ["run", str(tmp_path / "pkg"), "--input", '{"text":"hi"}', "--trace-root", str(trace_root)],
    )
    result = runner.invoke(
        app,
        ["traces-prune", "--older-than", "1", "--trace-root", str(trace_root)],
    )
    assert result.exit_code == 0
    assert "No traces to prune" in result.output


def test_traces_prune_dry_run(tmp_path: Path) -> None:
    trace_root = tmp_path / "traces"
    # Write an old trace directly
    trace_root.mkdir(parents=True)
    import json as _json
    (trace_root / "old__20200101T000000Z.json").write_text(
        _json.dumps({"skill_id": "test", "started_at": "2020-01-01T00:00:00+00:00", "status": "ok", "nodes": []}),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["traces-prune", "--older-than", "1", "--trace-root", str(trace_root), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "Would remove" in result.output
    # File still exists
    assert (trace_root / "old__20200101T000000Z.json").exists()


# ── version / list-ops ───────────────────────────────────────────────


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "graphsmith" in result.output
    assert "1.0.0" in result.output


def test_list_ops() -> None:
    result = runner.invoke(app, ["list-ops"])
    assert result.exit_code == 0
    lines = result.output.strip().split("\n")
    assert len(lines) == 18
    assert "template.render" in result.output
    assert "text.normalize" in result.output
    assert "text.word_count" in result.output
    assert "text.reverse" in result.output
    assert "skill.invoke" in result.output
    assert "llm.generate" in result.output
    # Should be sorted
    assert lines == sorted(lines)
