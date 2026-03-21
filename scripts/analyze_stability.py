#!/usr/bin/env python3
"""Analyze stability eval results from repeated runs.

Usage:
    python scripts/analyze_stability.py /tmp/gs_stability_*/
    python scripts/analyze_stability.py /tmp/gs_stability_20260320_150000/
"""
import json
import sys
from pathlib import Path


def _classify_failure(d: dict) -> str:
    checks = d.get("checks", {})
    if not checks.get("parsed", True) or not checks.get("has_graph", True):
        return "parse_error"
    if not checks.get("validates", True):
        return "validation_error"
    if not checks.get("correct_skills", True) and not checks.get("correct_outputs", True):
        return "wrong_skill_and_output"
    if not checks.get("correct_skills", True):
        return "wrong_skill_selection"
    if not checks.get("correct_outputs", True):
        return "wrong_output_name"
    if not checks.get("min_nodes_met", True):
        return "too_few_nodes"
    if not checks.get("no_holes", True):
        return "has_holes"
    return "other"


def analyze_directory(dirpath: str) -> None:
    d = Path(dirpath)
    if not d.is_dir():
        print(f"Not a directory: {dirpath}")
        return

    # Discover runs
    files = sorted(d.glob("run*_*.json"))
    if not files:
        print(f"No run files found in {dirpath}")
        return

    # Parse run structure
    runs: dict[int, dict[str, list[dict]]] = {}
    for f in files:
        name = f.stem  # e.g. run1_goals
        parts = name.split("_", 1)
        run_num = int(parts[0].replace("run", ""))
        set_name = parts[1] if len(parts) > 1 else "unknown"
        data = json.loads(f.read_text())
        if run_num not in runs:
            runs[run_num] = {}
        runs[run_num][set_name] = data

    num_runs = len(runs)
    all_sets = sorted(set(s for r in runs.values() for s in r))

    print(f"\n{'=' * 70}")
    print(f"STABILITY ANALYSIS: {dirpath}")
    print(f"{'=' * 70}")
    print(f"Runs: {num_runs}")
    print(f"Sets: {', '.join(all_sets)}")
    print()

    # Per-set stats
    for set_name in all_sets:
        passed_counts = []
        totals = []
        for run_num in sorted(runs.keys()):
            results = runs[run_num].get(set_name, [])
            p = sum(1 for r in results if r["status"] == "pass")
            t = len(results)
            passed_counts.append(p)
            totals.append(t)

        if not passed_counts:
            continue

        total = totals[0] if totals else 0
        rates = [p / t if t > 0 else 0 for p, t in zip(passed_counts, totals)]
        label = set_name.replace("_", " ")
        print(f"  {label} ({total} goals):")
        print(f"    Pass counts: {passed_counts}")
        print(f"    Min: {min(passed_counts)}/{total}  Max: {max(passed_counts)}/{total}  "
              f"Mean: {sum(passed_counts)/len(passed_counts):.1f}/{total}")
        print()

    # Per-goal stability
    goal_results: dict[str, list[str]] = {}
    goal_failures: dict[str, list[str]] = {}
    for run_num in sorted(runs.keys()):
        for set_name, results in runs[run_num].items():
            for r in results:
                goal = r["goal"]
                if goal not in goal_results:
                    goal_results[goal] = []
                    goal_failures[goal] = []
                goal_results[goal].append(r["status"])
                if r["status"] != "pass":
                    goal_failures[goal].append(_classify_failure(r))

    always_pass = []
    always_fail = []
    intermittent = []
    for goal in sorted(goal_results.keys()):
        statuses = goal_results[goal]
        passes = sum(1 for s in statuses if s == "pass")
        if passes == len(statuses):
            always_pass.append(goal)
        elif passes == 0:
            always_fail.append(goal)
        else:
            fcs = goal_failures.get(goal, [])
            dominant = max(set(fcs), key=fcs.count) if fcs else "?"
            intermittent.append((goal, passes, len(statuses), dominant))

    total_goals = len(goal_results)
    print(f"  GOAL STABILITY ({total_goals} goals):")
    print(f"    Always pass: {len(always_pass)}")
    print(f"    Always fail: {len(always_fail)}")
    print(f"    Intermittent: {len(intermittent)}")
    print()

    if always_fail:
        print(f"  ALWAYS FAILING ({len(always_fail)}):")
        for goal in always_fail:
            fcs = goal_failures.get(goal, [])
            dominant = max(set(fcs), key=fcs.count) if fcs else "?"
            print(f"    - {goal} [{dominant}]")
        print()

    if intermittent:
        print(f"  INTERMITTENT ({len(intermittent)}):")
        for goal, passes, total, dominant in sorted(intermittent, key=lambda x: x[1]):
            print(f"    - {goal} ({passes}/{total} pass) [{dominant}]")
        print()

    # Failure class distribution
    all_fc: dict[str, int] = {}
    for fcs in goal_failures.values():
        for fc in fcs:
            all_fc[fc] = all_fc.get(fc, 0) + 1
    if all_fc:
        print(f"  FAILURE CLASS DISTRIBUTION:")
        for fc, count in sorted(all_fc.items(), key=lambda x: -x[1]):
            print(f"    {count:3d}x  {fc}")
        print()

    # Overall
    all_passed = [sum(1 for r in results if r["status"] == "pass")
                  for run_data in runs.values() for results in [
                      [r for s in run_data.values() for r in s]
                  ]]
    all_totals = [sum(len(s) for s in run_data.values()) for run_data in runs.values()]
    if all_passed and all_totals:
        rates = [p / t if t > 0 else 0 for p, t in zip(all_passed, all_totals)]
        print(f"  OVERALL:")
        print(f"    Total pass rates: {[f'{r:.0%}' for r in rates]}")
        print(f"    Range: {min(rates):.0%} - {max(rates):.0%}")
        print(f"    Mean: {sum(rates)/len(rates):.0%}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/analyze_stability.py <dir> [...]")
        sys.exit(1)
    for arg in sys.argv[1:]:
        analyze_directory(arg)
