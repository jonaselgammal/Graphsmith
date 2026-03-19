#!/usr/bin/env python3
"""Inspect retrieval diagnostics from saved eval files.

Usage:
    python scripts/inspect_diagnostics.py /tmp/gs_diag_holdout.json
    python scripts/inspect_diagnostics.py /tmp/gs_holdout_*.json
"""
import json
import sys
from pathlib import Path


def inspect(path: str) -> None:
    data = json.loads(Path(path).read_text())
    name = Path(path).stem
    total = len(data)
    passes = [d for d in data if d["status"] == "pass"]
    fails = [d for d in data if d["status"] != "pass"]
    passed = len(passes)

    # Classify failures
    provider_fails = []
    retrieval_fails = []
    planner_fails = []
    for f in fails:
        ft = f.get("failure_type") or _infer_failure_type(f)
        if ft == "provider":
            provider_fails.append(f)
        elif ft == "retrieval":
            retrieval_fails.append(f)
        else:
            planner_fails.append(f)

    print(f"{'=' * 65}")
    print(f"{name}: {passed}/{total} pass ({100 * passed // total if total else 0}%)")
    print(f"{'=' * 65}")

    if provider_fails:
        print(f"  !! {len(provider_fails)} PROVIDER failures (429/rate-limit) -- run may be invalid")
    if retrieval_fails:
        print(f"  >> {len(retrieval_fails)} RETRIEVAL failures (needed skills not in shortlist)")
    if planner_fails:
        print(f"  ** {len(planner_fails)} PLANNER failures (skills present, wrong plan)")

    if not fails:
        print("  All goals passed.\n")
        return

    print()
    for f in fails:
        goal = f["goal"]
        status = f["status"]
        ft = f.get("failure_type") or _infer_failure_type(f)
        in_list = f.get("expected_in_shortlist", "?")
        retrieval = f.get("retrieval", {})
        shortlist = retrieval.get("candidates", [])
        cand_count = retrieval.get("candidate_count", "?")
        checks = f.get("checks", {})
        error = f.get("error", "")
        holes = f.get("holes", [])

        label = {"provider": "PROVIDER", "retrieval": "RETRIEVAL", "planner": "PLANNER"}.get(
            ft, ft.upper() if ft else "?"
        )
        print(f"  [{status.upper()}] [{label}] {goal}")
        print(f"    shortlist ({cand_count}): {shortlist}")
        print(f"    expected_in_shortlist: {in_list}")

        check_fails = [k for k, v in checks.items() if v is False]
        if check_fails:
            print(f"    failed checks: {', '.join(check_fails)}")
        if error:
            print(f"    error: {error[:150]}")
        if holes:
            for h in holes[:3]:
                print(f"    hole: {h[:120]}")
        print()


def _infer_failure_type(f: dict) -> str:
    """Infer failure type from content when the field is missing or empty."""
    try:
        from graphsmith.evaluation.diagnostics import infer_failure_type
        return infer_failure_type(f)
    except ImportError:
        # Fallback for running outside installed package
        error = (f.get("error") or "").lower()
        holes_text = " ".join(f.get("holes", [])).lower()
        _sigs = ["429", "rate limit", "provider error", "credit balance",
                 "api key", "authentication", "unauthorized", "api error",
                 "connect", "timeout"]
        if any(s in error or s in holes_text for s in _sigs):
            return "provider"
        if f.get("expected_in_shortlist") is False:
            return "retrieval"
        return "planner"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/inspect_diagnostics.py <diagnostics.json> [...]")
        sys.exit(1)

    for path in sys.argv[1:]:
        try:
            inspect(path)
        except FileNotFoundError:
            print(f"File not found: {path}")
        except Exception as e:
            print(f"Error reading {path}: {e}")
