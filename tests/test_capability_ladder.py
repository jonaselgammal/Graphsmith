"""Tests for capability ladder evaluation harness."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from graphsmith.evaluation.capability_ladder import (
    LadderTask,
    TaskResult,
    _outputs_match,
    format_report,
    load_ladder_tasks,
    run_campaign,
    run_task_with_mock,
    summarize_results,
)

TASKS_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "capability_ladder" / "tasks.json"


class TestLoadTasks:
    def test_loads_all_tasks(self) -> None:
        tasks = load_ladder_tasks(TASKS_PATH)
        assert len(tasks) >= 15

    def test_has_all_levels(self) -> None:
        tasks = load_ladder_tasks(TASKS_PATH)
        levels = {t.level for t in tasks}
        assert levels == {1, 2, 3, 4, 5}

    def test_task_fields(self) -> None:
        tasks = load_ladder_tasks(TASKS_PATH)
        for t in tasks:
            assert t.id
            assert t.goal
            assert t.level >= 1


class TestOutputsMatch:
    def test_exact_match(self) -> None:
        assert _outputs_match({"a": "hello"}, {"a": "hello"}, 0)

    def test_mismatch(self) -> None:
        assert not _outputs_match({"a": "hello"}, {"a": "world"}, 0)

    def test_numeric_tolerance(self) -> None:
        assert _outputs_match({"a": "2.5"}, {"a": "2.500001"}, 0.01)

    def test_numeric_outside_tolerance(self) -> None:
        assert not _outputs_match({"a": "2.5"}, {"a": "3.0"}, 0.01)

    def test_missing_key(self) -> None:
        assert not _outputs_match({"a": "1"}, {}, 0)


class TestRunSingleTask:
    def test_level1_normalize(self) -> None:
        task = LadderTask(
            id="test-L1", level=1, goal="Normalize this text",
            input={"text": "  Hello  WORLD  "},
            expected_output={"normalized": "hello world"},
            expected_skills=["text.normalize.v1"],
        )
        result = run_task_with_mock(task)
        assert result.status == "pass"

    def test_level1_math_add(self) -> None:
        task = LadderTask(
            id="test-add", level=1, goal="Add numbers",
            input={"a": "5", "b": "3"},
            expected_output={"result": "8"},
            expected_skills=["math.add.v1"],
        )
        result = run_task_with_mock(task)
        assert result.status == "pass"

    def test_level3_closed_loop_median(self) -> None:
        task = LadderTask(
            id="test-median", level=3, goal="Compute the median of these numbers",
            input={"values": "3\n1\n2"},
            expected_output={"result": "2"},
            expected_skills=["math.median.v1"],
            closed_loop=True,
        )
        result = run_task_with_mock(task)
        assert result.status == "pass"
        assert result.closed_loop_used
        assert result.generated_skill == "math.median.v1"

    def test_level3_closed_loop_uppercase(self) -> None:
        task = LadderTask(
            id="test-upper", level=3, goal="Uppercase this text",
            input={"text": "hello"},
            expected_output={"uppercased": "HELLO"},
            expected_skills=["text.uppercase.v1"],
            closed_loop=True,
        )
        result = run_task_with_mock(task)
        assert result.status == "pass"
        assert result.generated_skill == "text.uppercase.v1"


class TestCampaign:
    def test_full_campaign(self) -> None:
        tasks = load_ladder_tasks(TASKS_PATH)
        results = run_campaign(tasks)
        summary = summarize_results(results)
        assert summary["total"] == len(tasks)
        assert summary["passed"] >= 15  # most should pass
        assert summary["closed_loop_used"] >= 6


class TestSummary:
    def test_summarize(self) -> None:
        results = [
            TaskResult(task_id="a", level=1, goal="test1", status="pass"),
            TaskResult(task_id="b", level=1, goal="test2", status="fail", failure_category="wrong_output"),
            TaskResult(task_id="c", level=2, goal="test3", status="pass", closed_loop_used=True),
        ]
        summary = summarize_results(results)
        assert summary["total"] == 3
        assert summary["passed"] == 2
        assert summary["levels"][1]["passed"] == 1
        assert summary["levels"][2]["passed"] == 1
        assert summary["failure_categories"]["wrong_output"] == 1

    def test_format_report(self) -> None:
        results = [
            TaskResult(task_id="a", level=1, goal="test", status="pass"),
        ]
        summary = summarize_results(results)
        text = format_report(results, summary)
        assert "Capability Ladder" in text
        assert "Level 1" in text
