#!/usr/bin/env python3
"""Run the full skill generation test suite.

Usage:
    python scripts/test_skill_generation.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graphsmith.skills.autogen import run_generation_suite


def main() -> None:
    print("\n  Skill Generation Test Suite")
    print("  " + "=" * 45)

    summary = run_generation_suite()

    print(f"\n  Templates tested: {summary['total']}")
    print(f"  Passed end-to-end: {summary['passed']}")
    print(f"  Validation failures: {summary['validation_failures']}")
    print(f"  Example failures: {summary['example_failures']}")
    print()

    for r in summary["results"]:
        key = r["template_key"]
        family = r.get("family", "")
        val = r["validation"]
        ex_pass = r["examples_passed"]
        ex_total = r["examples_total"]
        status = "PASS" if val == "PASS" and ex_pass == ex_total else "FAIL"
        mark = "\u2714" if status == "PASS" else "\u2716"
        print(f"  {mark} {key:20s} [{family:22s}]  val={val}  ex={ex_pass}/{ex_total}")
        if r["errors"]:
            for err in r["errors"][:2]:
                print(f"      {err[:80]}")

    print()
    if summary["passed"] == summary["total"]:
        print("  All templates pass.")
    else:
        print(f"  {summary['total'] - summary['passed']} template(s) have issues.")
    print()


if __name__ == "__main__":
    main()
