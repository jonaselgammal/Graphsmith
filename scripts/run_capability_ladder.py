#!/usr/bin/env python3
"""Run the capability ladder evaluation campaign.

Usage:
    python scripts/run_capability_ladder.py [--level N] [--save results.json]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graphsmith.evaluation.capability_ladder import (
    format_report,
    load_ladder_tasks,
    run_campaign,
    summarize_results,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run capability ladder evaluation")
    parser.add_argument("--level", type=int, help="Run only this level")
    parser.add_argument("--save", type=str, help="Save results JSON to this path")
    parser.add_argument("--tasks", type=str,
                        default="evaluation/capability_ladder/tasks.json",
                        help="Path to tasks JSON file")
    args = parser.parse_args()

    tasks = load_ladder_tasks(args.tasks)
    if args.level is not None:
        tasks = [t for t in tasks if t.level == args.level]

    print(f"\nRunning {len(tasks)} tasks...\n")
    results = run_campaign(tasks)
    summary = summarize_results(results)

    print(format_report(results, summary))

    if args.save:
        Path(args.save).write_text(json.dumps(
            {"summary": summary, "results": [r.model_dump() for r in results]},
            indent=2,
        ))
        print(f"\nSaved to {args.save}")


if __name__ == "__main__":
    main()
