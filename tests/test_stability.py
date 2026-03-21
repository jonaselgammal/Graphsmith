"""Tests for IR Sprint 8: stability evaluation and trace export."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from graphsmith.evaluation.planner_eval import EvalChecks, EvalReport, EvalResult
from graphsmith.evaluation.stability import (
    GoalStability,
    StabilityReport,
    TraceRecord,
    aggregate_stability,
    classify_failure,
    export_traces,
    load_traces,
    print_stability_report,
)


# ── Failure classification ─────────────────────────────────────────


class TestClassifyFailure:
    def _make_result(self, **check_overrides) -> EvalResult:
        defaults = dict(parsed=True, has_graph=True, validates=True,
                        correct_skills=True, correct_outputs=True,
                        min_nodes_met=True, no_holes=True)
        defaults.update(check_overrides)
        return EvalResult(
            goal="test", status="partial" if any(not v for v in defaults.values()) else "pass",
            checks=EvalChecks(**defaults),
        )

    def test_pass_returns_empty(self) -> None:
        r = self._make_result()
        r.status = "pass"
        assert classify_failure(r) == ""

    def test_wrong_output_name(self) -> None:
        r = self._make_result(correct_outputs=False)
        assert classify_failure(r) == "wrong_output_name"

    def test_wrong_skill_selection(self) -> None:
        r = self._make_result(correct_skills=False)
        assert classify_failure(r) == "wrong_skill_selection"

    def test_wrong_both(self) -> None:
        r = self._make_result(correct_skills=False, correct_outputs=False)
        assert classify_failure(r) == "wrong_skill_and_output"

    def test_parse_error(self) -> None:
        r = self._make_result(parsed=False, has_graph=False)
        assert classify_failure(r) == "parse_error"

    def test_validation_error(self) -> None:
        r = self._make_result(validates=False)
        assert classify_failure(r) == "validation_error"


# ── Trace export/import ───────────────────────────────────────────


class TestTraceExport:
    def test_export_and_load_roundtrip(self) -> None:
        traces = [
            TraceRecord(run_index=0, goal="test 1", status="pass"),
            TraceRecord(run_index=0, goal="test 2", status="fail",
                        failure_class="wrong_output_name"),
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        export_traces(traces, path)
        loaded = load_traces(path)

        assert len(loaded) == 2
        assert loaded[0].goal == "test 1"
        assert loaded[0].status == "pass"
        assert loaded[1].failure_class == "wrong_output_name"
        Path(path).unlink()

    def test_trace_record_fields(self) -> None:
        t = TraceRecord(
            run_index=1,
            goal="extract keywords",
            model="llama-3.1-8b",
            backend="ir",
            candidate_count=3,
            use_decomposition=True,
            status="pass",
            graph_nodes=["extract:text.extract_keywords.v1"],
            graph_outputs={"keywords": "extract.keywords"},
        )
        d = t.model_dump()
        assert d["run_index"] == 1
        assert d["candidate_count"] == 3
        assert d["use_decomposition"] is True
        assert len(d["graph_nodes"]) == 1

    def test_jsonl_format(self) -> None:
        traces = [TraceRecord(run_index=0, goal="g1"), TraceRecord(run_index=1, goal="g2")]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w") as f:
            path = f.name

        export_traces(traces, path)
        lines = Path(path).read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            json.loads(line)  # should not raise
        Path(path).unlink()


# ── Stability aggregation ─────────────────────────────────────────


class TestStabilityAggregation:
    def _make_report(self, goals_passed: int, total: int, results: list[EvalResult]) -> EvalReport:
        return EvalReport(
            provider="test", model="test",
            goals_total=total, goals_passed=goals_passed,
            pass_rate=goals_passed / total if total > 0 else 0.0,
            results=results,
        )

    def _make_results(self, statuses: list[tuple[str, str]]) -> list[EvalResult]:
        results = []
        for goal, status in statuses:
            checks = EvalChecks(
                parsed=True, has_graph=True, validates=True,
                correct_skills=True, correct_outputs=(status == "pass"),
                min_nodes_met=True, no_holes=True,
            )
            results.append(EvalResult(
                goal=goal, status=status, checks=checks,
            ))
        return results

    def test_all_pass_stability(self) -> None:
        results = self._make_results([("g1", "pass"), ("g2", "pass")])
        reports = [
            self._make_report(2, 2, results),
            self._make_report(2, 2, results),
        ]
        s = aggregate_stability(reports)
        assert s.num_runs == 2
        assert s.always_pass == 2
        assert s.always_fail == 0
        assert s.intermittent == 0
        assert s.min_pass_rate == 1.0
        assert s.max_pass_rate == 1.0

    def test_intermittent_goal(self) -> None:
        r1 = self._make_results([("g1", "pass"), ("g2", "pass")])
        r2 = self._make_results([("g1", "pass"), ("g2", "partial")])
        reports = [
            self._make_report(2, 2, r1),
            self._make_report(1, 2, r2),
        ]
        s = aggregate_stability(reports)
        assert s.always_pass == 1  # g1
        assert s.intermittent == 1  # g2
        assert s.always_fail == 0

    def test_always_fail_goal(self) -> None:
        r1 = self._make_results([("g1", "partial"), ("g2", "pass")])
        r2 = self._make_results([("g1", "partial"), ("g2", "pass")])
        reports = [
            self._make_report(1, 2, r1),
            self._make_report(1, 2, r2),
        ]
        s = aggregate_stability(reports)
        assert s.always_pass == 1
        assert s.always_fail == 1

    def test_dominant_failure(self) -> None:
        r1 = self._make_results([("g1", "partial")])
        r2 = self._make_results([("g1", "partial")])
        r3 = self._make_results([("g1", "pass")])
        reports = [
            self._make_report(0, 1, r1),
            self._make_report(0, 1, r2),
            self._make_report(1, 1, r3),
        ]
        s = aggregate_stability(reports)
        assert s.intermittent == 1
        gs = s.goal_stability[0]
        assert gs.dominant_failure == "wrong_output_name"
        assert gs.passes == 1
        assert gs.total_runs == 3

    def test_pass_rate_stats(self) -> None:
        r1 = self._make_results([("g1", "pass"), ("g2", "pass"), ("g3", "pass")])
        r2 = self._make_results([("g1", "pass"), ("g2", "partial"), ("g3", "pass")])
        r3 = self._make_results([("g1", "pass"), ("g2", "partial"), ("g3", "partial")])
        reports = [
            self._make_report(3, 3, r1),
            self._make_report(2, 3, r2),
            self._make_report(1, 3, r3),
        ]
        s = aggregate_stability(reports)
        assert abs(s.min_pass_rate - 1/3) < 0.01
        assert abs(s.max_pass_rate - 1.0) < 0.01
        assert abs(s.mean_pass_rate - 2/3) < 0.01

    def test_empty_reports(self) -> None:
        s = aggregate_stability([])
        assert s.num_runs == 0


# ── Report printing ──────────────────────────────────────────────


class TestPrintReport:
    def test_print_non_empty(self) -> None:
        s = StabilityReport(
            model="test", backend="ir", num_runs=3,
            min_pass_rate=0.8, max_pass_rate=1.0, mean_pass_rate=0.9, median_pass_rate=0.9,
            always_pass=30, intermittent=4, always_fail=2,
            goal_stability=[
                GoalStability(goal="bad", total_runs=3, passes=0, stability="always_fail",
                              dominant_failure="wrong_output_name"),
                GoalStability(goal="flaky", total_runs=3, passes=2, pass_rate=0.67,
                              stability="intermittent", dominant_failure="wrong_output_name"),
            ],
        )
        text = print_stability_report(s)
        assert "test" in text
        assert "always pass" in text.lower() or "Always failing" in text
        assert "bad" in text
        assert "flaky" in text
