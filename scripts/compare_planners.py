#!/usr/bin/env python3
"""Compare diagnostics from two planner runs (direct vs IR).

Usage:
    python scripts/compare_planners.py /tmp/gs_llm_diag_goals.json /tmp/gs_ir_diag_goals.json
    python scripts/compare_planners.py /tmp/gs_llm_diag_*.json /tmp/gs_ir_diag_*.json  (multiple pairs)
"""
import json
import sys
from pathlib import Path


def _infer_failure_type(f: dict) -> str:
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


def _classify_checks(f: dict) -> list[str]:
    """Classify failure based on which checks failed."""
    checks = f.get("checks", {})
    issues = []
    if checks.get("parsed") is False:
        issues.append("parse_failed")
    if checks.get("has_graph") is False:
        issues.append("no_graph")
    if checks.get("validates") is False:
        issues.append("validation_failed")
    if checks.get("correct_skills") is False:
        issues.append("wrong_skills")
    if checks.get("correct_outputs") is False:
        issues.append("wrong_outputs")
    if checks.get("min_nodes_met") is False:
        issues.append("too_few_nodes")
    if checks.get("no_holes") is False:
        issues.append("has_holes")
    return issues


def compare_files(path_a: str, path_b: str) -> dict:
    """Compare two diagnostics files."""
    data_a = json.loads(Path(path_a).read_text())
    data_b = json.loads(Path(path_b).read_text())

    name_a = Path(path_a).stem
    name_b = Path(path_b).stem

    # Build goal -> result maps
    map_a = {d["goal"]: d for d in data_a}
    map_b = {d["goal"]: d for d in data_b}
    all_goals = sorted(set(map_a.keys()) | set(map_b.keys()))

    pass_a = sum(1 for d in data_a if d["status"] == "pass")
    pass_b = sum(1 for d in data_b if d["status"] == "pass")
    total_a = len(data_a)
    total_b = len(data_b)

    print(f"\n{'=' * 70}")
    print(f"COMPARISON: {name_a} vs {name_b}")
    print(f"{'=' * 70}")
    print(f"  {name_a}: {pass_a}/{total_a} pass ({100 * pass_a // total_a if total_a else 0}%)")
    print(f"  {name_b}: {pass_b}/{total_b} pass ({100 * pass_b // total_b if total_b else 0}%)")
    print()

    # Detailed per-goal comparison
    improved = []
    regressed = []
    both_pass = []
    both_fail = []

    for goal in all_goals:
        ra = map_a.get(goal, {})
        rb = map_b.get(goal, {})
        sa = ra.get("status", "missing")
        sb = rb.get("status", "missing")

        if sa == "pass" and sb == "pass":
            both_pass.append(goal)
        elif sa != "pass" and sb == "pass":
            improved.append((goal, ra, rb))
        elif sa == "pass" and sb != "pass":
            regressed.append((goal, ra, rb))
        else:
            both_fail.append((goal, ra, rb))

    if improved:
        print(f"  IMPROVED ({len(improved)} goals — {name_b} fixed what {name_a} failed):")
        for goal, ra, rb in improved:
            ft = ra.get("failure_type") or _infer_failure_type(ra)
            issues = _classify_checks(ra)
            print(f"    + {goal}")
            print(f"      was: [{ft}] {', '.join(issues)}")
        print()

    if regressed:
        print(f"  REGRESSED ({len(regressed)} goals — {name_b} broke what {name_a} passed):")
        for goal, ra, rb in regressed:
            ft = rb.get("failure_type") or _infer_failure_type(rb)
            issues = _classify_checks(rb)
            error = rb.get("error", "")
            print(f"    - {goal}")
            print(f"      now: [{ft}] {', '.join(issues)}")
            if error:
                print(f"      error: {error[:150]}")
        print()

    if both_fail:
        print(f"  BOTH FAIL ({len(both_fail)} goals):")
        for goal, ra, rb in both_fail:
            ft_a = ra.get("failure_type") or _infer_failure_type(ra)
            ft_b = rb.get("failure_type") or _infer_failure_type(rb)
            iss_a = _classify_checks(ra)
            iss_b = _classify_checks(rb)
            print(f"    x {goal}")
            print(f"      {name_a}: [{ft_a}] {', '.join(iss_a)}")
            print(f"      {name_b}: [{ft_b}] {', '.join(iss_b)}")
        print()

    if both_pass:
        print(f"  BOTH PASS ({len(both_pass)} goals): {', '.join(g[:30] for g in both_pass[:5])}")
        if len(both_pass) > 5:
            print(f"    ... and {len(both_pass) - 5} more")
        print()

    # Failure type summary
    types_a: dict[str, int] = {}
    types_b: dict[str, int] = {}
    for d in data_a:
        if d["status"] != "pass":
            ft = d.get("failure_type") or _infer_failure_type(d)
            types_a[ft] = types_a.get(ft, 0) + 1
    for d in data_b:
        if d["status"] != "pass":
            ft = d.get("failure_type") or _infer_failure_type(d)
            types_b[ft] = types_b.get(ft, 0) + 1

    if types_a or types_b:
        print(f"  FAILURE TYPE SUMMARY:")
        all_types = sorted(set(types_a.keys()) | set(types_b.keys()))
        for ft in all_types:
            ca = types_a.get(ft, 0)
            cb = types_b.get(ft, 0)
            arrow = "→" if ca != cb else "="
            print(f"    {ft:12s}: {ca} {arrow} {cb}")
        print()

    return {
        "pass_a": pass_a, "pass_b": pass_b,
        "total": max(total_a, total_b),
        "improved": len(improved),
        "regressed": len(regressed),
        "both_fail": len(both_fail),
        "both_pass": len(both_pass),
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/compare_planners.py <direct_diag.json> <ir_diag.json>")
        print("       python scripts/compare_planners.py /tmp/gs_llm_diag_*.json /tmp/gs_ir_diag_*.json")
        sys.exit(1)

    args = sys.argv[1:]
    # Auto-pair: if we have an even number, pair them; otherwise just compare first two
    if len(args) == 2:
        compare_files(args[0], args[1])
    elif len(args) % 2 == 0:
        mid = len(args) // 2
        for a, b in zip(args[:mid], args[mid:]):
            compare_files(a, b)
    else:
        print(f"Expected even number of files to compare, got {len(args)}")
        sys.exit(1)
