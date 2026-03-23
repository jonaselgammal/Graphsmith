"""Trace persistence — one JSON file per run."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from graphsmith.traces.models import RunTrace

_DEFAULT_ROOT = Path.home() / ".graphsmith" / "traces"


class TraceStore:
    """Read and write RunTrace files on disk."""

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root) if root else _DEFAULT_ROOT

    @property
    def root(self) -> Path:
        return self._root

    def save(self, trace: RunTrace) -> str:
        """Persist a trace and return its trace_id."""
        self._root.mkdir(parents=True, exist_ok=True)
        trace_id = _make_trace_id(trace)
        path = self._root / f"{trace_id}.json"
        path.write_text(
            json.dumps(trace.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )
        return trace_id

    def load(self, trace_id: str) -> dict[str, Any]:
        """Load a trace by ID. Returns the raw dict."""
        path = self._root / f"{trace_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Trace not found: {trace_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_ids(self) -> list[str]:
        """Return all trace IDs, sorted."""
        if not self._root.exists():
            return []
        return [p.stem for p in sorted(self._root.glob("*.json"))]

    def list_summaries(self) -> list[dict[str, Any]]:
        """Return compact summaries for all traces.

        Invalid/unreadable trace files are skipped to keep listing robust.
        """
        summaries: list[dict[str, Any]] = []
        for trace_id in self.list_ids():
            try:
                summaries.append(self.summarise(trace_id))
            except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
                continue
        return summaries

    def prune(self, older_than_days: int, *, dry_run: bool = False) -> list[str]:
        """Remove traces older than *older_than_days*.

        Returns list of removed (or would-be-removed) trace IDs.
        Only removes files with a parseable started_at timestamp.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        removed: list[str] = []

        for trace_id in self.list_ids():
            path = self._root / f"{trace_id}.json"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                started = data.get("started_at", "")
                ts = datetime.fromisoformat(started)
                if ts < cutoff:
                    if not dry_run:
                        path.unlink()
                    removed.append(trace_id)
            except (json.JSONDecodeError, ValueError, KeyError, OSError):
                # Unparseable files are left untouched
                continue

        return removed

    def summarise(self, trace_id: str) -> dict[str, Any]:
        """Return a compact summary of a trace."""
        data = self.load(trace_id)
        nodes = data.get("nodes", [])
        child_count = sum(1 for n in nodes if n.get("child_trace"))
        ops = [n.get("op", "?") for n in nodes]
        sig = " -> ".join(ops) if ops else "(empty)"

        duration = None
        started = data.get("started_at")
        ended = data.get("ended_at")
        if started and ended:
            try:
                t0 = datetime.fromisoformat(started)
                t1 = datetime.fromisoformat(ended)
                duration = f"{(t1 - t0).total_seconds():.3f}s"
            except ValueError:
                pass

        return {
            "trace_id": trace_id,
            "skill_id": data.get("skill_id", "?"),
            "started_at": started,
            "status": data.get("status", "?"),
            "duration": duration,
            "node_count": len(nodes),
            "child_trace_count": child_count,
            "op_signature": sig,
            "input_keys": sorted(data.get("inputs_summary", {}).keys()),
            "output_keys": sorted(data.get("outputs_summary", {}).keys()),
        }


def _make_trace_id(trace: RunTrace) -> str:
    """Build a filesystem-safe trace ID from the trace metadata."""
    ts = trace.started_at or "unknown"
    ts_compact = re.sub(r"[:\-+.]", "", ts)[:20]
    safe_skill = trace.skill_id.replace("/", "_")
    return f"{safe_skill}__{ts_compact}"
