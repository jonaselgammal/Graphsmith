"""Tests for trace persistence, listing, loading, and promotion candidates."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.parser import load_skill_package
from graphsmith.runtime import run_skill_package
from graphsmith.traces import TraceStore, find_promotion_candidates
from graphsmith.traces.models import NodeTrace, RunTrace, _now_iso
from graphsmith.traces.promotion import PromotionCandidate
from graphsmith.validator import validate_skill_package

from conftest import EXAMPLE_DIR, minimal_examples, minimal_graph, minimal_skill, write_package


@pytest.fixture()
def store(tmp_path: Path) -> TraceStore:
    return TraceStore(root=tmp_path / "traces")


def _run_minimal(tmp_path: Path, *, text: str = "hello") -> RunTrace:
    """Run the minimal package and return its trace."""
    write_package(
        tmp_path / "pkg",
        skill=minimal_skill(),
        graph=minimal_graph(),
        examples=minimal_examples(),
    )
    pkg = load_skill_package(tmp_path / "pkg")
    validate_skill_package(pkg)
    result = run_skill_package(pkg, {"text": text})
    return result.trace


def _run_summarize() -> RunTrace:
    """Run the summarize example with mock LLM and return its trace."""
    pkg = load_skill_package(EXAMPLE_DIR / "text.summarize.v1")
    validate_skill_package(pkg)
    provider = EchoLLMProvider(prefix="")
    result = run_skill_package(
        pkg, {"text": "hello", "max_sentences": 1}, llm_provider=provider,
    )
    return result.trace


# ── trace store ──────────────────────────────────────────────────────


class TestTraceStore:
    def test_save_and_load(self, store: TraceStore, tmp_path: Path) -> None:
        trace = _run_minimal(tmp_path / "run1")
        tid = store.save(trace)
        loaded = store.load(tid)
        assert loaded["skill_id"] == "test.minimal.v1"
        assert loaded["status"] == "ok"
        assert len(loaded["nodes"]) == 1

    def test_save_creates_file(self, store: TraceStore, tmp_path: Path) -> None:
        trace = _run_minimal(tmp_path / "run1")
        tid = store.save(trace)
        assert (store.root / f"{tid}.json").exists()

    def test_list_empty(self, store: TraceStore) -> None:
        assert store.list_ids() == []

    def test_list_after_saves(self, store: TraceStore, tmp_path: Path) -> None:
        t1 = _run_minimal(tmp_path / "run1", text="a")
        t2 = _run_minimal(tmp_path / "run2", text="b")
        store.save(t1)
        store.save(t2)
        ids = store.list_ids()
        assert len(ids) == 2

    def test_load_not_found(self, store: TraceStore) -> None:
        with pytest.raises(FileNotFoundError):
            store.load("nonexistent")

    def test_save_error_trace(self, store: TraceStore) -> None:
        trace = RunTrace(
            skill_id="test.fail",
            started_at=_now_iso(),
            ended_at=_now_iso(),
            status="error",
            error="something broke",
        )
        tid = store.save(trace)
        loaded = store.load(tid)
        assert loaded["status"] == "error"
        assert loaded["error"] == "something broke"

    def test_save_summarize_with_nested(self, store: TraceStore) -> None:
        trace = _run_summarize()
        tid = store.save(trace)
        loaded = store.load(tid)
        assert loaded["skill_id"] == "text.summarize.v1"
        assert len(loaded["nodes"]) == 2


# ── promotion candidates ─────────────────────────────────────────────


class TestPromotionCandidates:
    def test_no_traces_no_candidates(self, store: TraceStore) -> None:
        candidates = find_promotion_candidates(store)
        assert candidates == []

    def test_single_trace_no_candidates(
        self, store: TraceStore, tmp_path: Path
    ) -> None:
        trace = _run_minimal(tmp_path / "run1")
        store.save(trace)
        candidates = find_promotion_candidates(store, min_frequency=2)
        assert candidates == []

    def test_repeated_traces_produce_candidate(
        self, store: TraceStore, tmp_path: Path
    ) -> None:
        for i in range(3):
            trace = _run_minimal(tmp_path / f"run{i}", text=f"input_{i}")
            store.save(trace)
        candidates = find_promotion_candidates(store, min_frequency=2)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.signature == "template.render"
        assert c.structural_signature == "template.render"
        assert c.frequency == 3
        assert len(c.trace_ids) == 3
        assert "text" in c.inferred_inputs
        assert "result" in c.inferred_outputs
        assert c.suggested_skill_id.startswith("promoted.")
        assert c.confidence > 0.0

    def test_different_signatures_grouped_separately(
        self, store: TraceStore, tmp_path: Path
    ) -> None:
        # 2x minimal (template.render)
        for i in range(2):
            trace = _run_minimal(tmp_path / f"min{i}")
            store.save(trace)
        # 2x summarize (template.render -> llm.generate)
        for i in range(2):
            trace = _run_summarize()
            store.save(trace)
        candidates = find_promotion_candidates(store, min_frequency=2)
        sigs = [c.signature for c in candidates]
        assert "template.render" in sigs
        assert "template.render -> llm.generate" in sigs

    def test_min_frequency_filters(
        self, store: TraceStore, tmp_path: Path
    ) -> None:
        for i in range(2):
            trace = _run_minimal(tmp_path / f"run{i}")
            store.save(trace)
        assert len(find_promotion_candidates(store, min_frequency=2)) == 1
        assert len(find_promotion_candidates(store, min_frequency=3)) == 0

    def test_deterministic_order(
        self, store: TraceStore, tmp_path: Path
    ) -> None:
        for i in range(3):
            trace = _run_minimal(tmp_path / f"run{i}")
            store.save(trace)
        a = find_promotion_candidates(store)
        b = find_promotion_candidates(store)
        assert [c.signature for c in a] == [c.signature for c in b]

    def test_candidate_model_fields(self) -> None:
        c = PromotionCandidate(
            signature="template.render -> llm.generate",
            ops=["template.render", "llm.generate"],
            frequency=5,
            trace_ids=["t1", "t2"],
            inferred_inputs=["text"],
            inferred_outputs=["summary"],
        )
        d = c.model_dump()
        assert d["signature"] == "template.render -> llm.generate"
        assert "confidence" in d
        assert d["frequency"] == 5
        assert "v2 heuristic" in d["notes"]


# ── trace summary ────────────────────────────────────────────────────


class TestTraceSummary:
    def test_summary_fields(self, store: TraceStore, tmp_path: Path) -> None:
        trace = _run_minimal(tmp_path / "run1")
        tid = store.save(trace)
        s = store.summarise(tid)
        assert s["trace_id"] == tid
        assert s["skill_id"] == "test.minimal.v1"
        assert s["started_at"] is not None
        assert s["status"] == "ok"
        assert s["node_count"] == 1
        assert s["child_trace_count"] == 0
        assert s["op_signature"] == "template.render"
        assert "text" in s["input_keys"]
        assert "result" in s["output_keys"]

    def test_summary_duration(self, store: TraceStore, tmp_path: Path) -> None:
        trace = _run_minimal(tmp_path / "run1")
        tid = store.save(trace)
        s = store.summarise(tid)
        assert s["duration"] is not None
        assert s["duration"].endswith("s")

    def test_summary_not_found(self, store: TraceStore) -> None:
        with pytest.raises(FileNotFoundError):
            store.summarise("nonexistent")

    def test_list_summaries(self, store: TraceStore, tmp_path: Path) -> None:
        trace = _run_minimal(tmp_path / "run1")
        tid = store.save(trace)
        items = store.list_summaries()
        assert len(items) == 1
        assert items[0]["trace_id"] == tid


# ── trace pruning ────────────────────────────────────────────────────


class TestTracePrune:
    def test_prune_removes_old_traces(
        self, store: TraceStore, tmp_path: Path
    ) -> None:
        """Create a trace with an old timestamp and prune it."""
        from graphsmith.traces.models import RunTrace
        old_trace = RunTrace(
            skill_id="test.old",
            started_at="2020-01-01T00:00:00+00:00",
            ended_at="2020-01-01T00:00:01+00:00",
            status="ok",
        )
        store.save(old_trace)
        # Also save a recent one
        recent = _run_minimal(tmp_path / "recent")
        store.save(recent)

        assert len(store.list_ids()) == 2
        removed = store.prune(older_than_days=1)
        assert len(removed) == 1
        assert "test.old" in removed[0]
        assert len(store.list_ids()) == 1

    def test_prune_dry_run(self, store: TraceStore) -> None:
        from graphsmith.traces.models import RunTrace
        old_trace = RunTrace(
            skill_id="test.old",
            started_at="2020-01-01T00:00:00+00:00",
            status="ok",
        )
        store.save(old_trace)

        removed = store.prune(older_than_days=1, dry_run=True)
        assert len(removed) == 1
        # File should still exist
        assert len(store.list_ids()) == 1

    def test_prune_nothing_to_remove(
        self, store: TraceStore, tmp_path: Path
    ) -> None:
        trace = _run_minimal(tmp_path / "run1")
        store.save(trace)
        removed = store.prune(older_than_days=1)
        assert removed == []
