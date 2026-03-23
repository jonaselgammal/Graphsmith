"""Tests for live campaign harness (deterministic, no LLM calls)."""
from __future__ import annotations

from pathlib import Path

import pytest

from graphsmith.evaluation.capability_ladder import LadderTask, load_ladder_tasks
from graphsmith.evaluation.live_campaign import (
    LiveTaskResult,
    format_live_report,
    summarize_by_bucket,
)


LIVE_TASKS_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "live_campaign" / "tasks.json"


class TestLoadLiveTasks:
    def test_loads_all_tasks(self) -> None:
        tasks = load_ladder_tasks(LIVE_TASKS_PATH)
        assert len(tasks) >= 20

    def test_has_all_buckets(self) -> None:
        tasks = load_ladder_tasks(LIVE_TASKS_PATH)
        buckets = {t.bucket for t in tasks}
        assert buckets == {"A", "B", "C", "D", "E"}

    def test_task_fields(self) -> None:
        tasks = load_ladder_tasks(LIVE_TASKS_PATH)
        for t in tasks:
            assert t.id
            assert t.goal
            assert t.bucket


class TestSummarizeByBucket:
    def test_bucket_summary(self) -> None:
        results = [
            LiveTaskResult(task_id="A01", level=1, goal="test", bucket="A", status="pass"),
            LiveTaskResult(task_id="A02", level=1, goal="test", bucket="A", status="fail"),
            LiveTaskResult(task_id="B01", level=2, goal="test", bucket="B", status="pass"),
        ]
        summary = summarize_by_bucket(results)
        assert summary["A"]["total"] == 2
        assert summary["A"]["passed"] == 1
        assert summary["B"]["passed"] == 1


class TestFormatLiveReport:
    def test_format_includes_buckets(self) -> None:
        results = [
            LiveTaskResult(task_id="A01", level=1, goal="test", bucket="A",
                          model="test-model", status="pass"),
        ]
        text = format_live_report(results)
        assert "Bucket A" in text
        assert "test-model" in text

    def test_format_shows_failures(self) -> None:
        results = [
            LiveTaskResult(task_id="C01", level=3, goal="test", bucket="C",
                          model="m", status="fail", failure_category="wrong_skills",
                          error="bad skills"),
        ]
        text = format_live_report(results)
        assert "wrong_skills" in text

    def test_format_shows_generated_skill(self) -> None:
        results = [
            LiveTaskResult(task_id="C02", level=3, goal="test", bucket="C",
                          model="m", status="pass", closed_loop_used=True,
                          generated_skill="math.min.v1"),
        ]
        text = format_live_report(results)
        assert "math.min.v1" in text


class TestLiveTaskResultModel:
    def test_all_fields(self) -> None:
        r = LiveTaskResult(
            task_id="X", level=1, goal="test", bucket="A", model="m",
            status="pass", closed_loop_used=True, generated_skill="math.foo.v1",
            decomposition={"content_transforms": ["normalize"]},
            candidate_count=3, plan_node_ids=["a", "b"],
        )
        assert r.candidate_count == 3
        assert r.generated_skill == "math.foo.v1"
