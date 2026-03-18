#!/usr/bin/env python3
"""Inspect retrieval diagnostics from saved eval files.

Usage:
    python scripts/inspect_diagnostics.py /tmp/gs_holdout_ranked.json
    python scripts/inspect_diagnostics.py /tmp/gs_holdout_*.json
"""
import json
import sys
from pathlib import Path


def inspect(path: str) -> None:
    data = json.loads(Path(path).read_text())
    name = Path(path).stem
    total = len(data)
    fails = [d for d in data if d["status"] != "pass"]
    passed = total - len(fails)

    print(f"{'=' * 60}")
    print(f"{name}: {passed}/{total} pass ({100*passed/total:.0f}%)")
    print(f"{'=' * 60}")

    if not fails:
        print("  All goals passed.\n")
        return

    for f in fails:
        goal = f["goal"]
        status = f["status"]
        in_list = f.get("expected_in_shortlist", "?")
        retrieval = f.get("retrieval", {})
        shortlist = retrieval.get("candidates", [])
        cand_count = retrieval.get("candidate_count", "?")
        tokens = retrieval.get("expanded_tokens", [])
        checks = f.get("checks", {})
        error = f.get("error", "")
        holes = f.get("holes", [])

        print(f"\n  [{status.upper()}] {goal}")
        print(f"    expected_in_shortlist: {in_list}")
        print(f"    candidates ({cand_count}): {shortlist}")
        print(f"    tokens: {tokens}")

        # Show which checks failed
        check_fails = [k for k, v in checks.items() if v is False]
        if check_fails:
            print(f"    failed checks: {', '.join(check_fails)}")
        if error:
            print(f"    error: {error[:150]}")
        if holes:
            for h in holes[:3]:
                print(f"    hole: {h[:120]}")

    print()


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
