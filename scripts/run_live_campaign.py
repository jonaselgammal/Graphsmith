#!/usr/bin/env python3
"""Run the live capability campaign with real LLM planning.

Usage:
    python scripts/run_live_campaign.py --provider anthropic --model claude-haiku-4-5-20251001
    python scripts/run_live_campaign.py --provider openai --model llama-3.1-8b-instant --base-url https://api.groq.com/openai/v1
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graphsmith.evaluation.capability_ladder import load_ladder_tasks
from graphsmith.evaluation.live_campaign import (
    format_live_report,
    run_live_campaign,
    summarize_by_bucket,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live capability campaign")
    parser.add_argument("--provider", default="anthropic", help="LLM provider")
    parser.add_argument("--model", default="claude-haiku-4-5-20251001", help="Model name")
    parser.add_argument("--base-url", default=None, help="Base URL for OpenAI-compatible")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between tasks")
    parser.add_argument("--save", type=str, help="Save results JSON to this path")
    parser.add_argument("--bucket", type=str, help="Run only this bucket (A/B/C/D/E)")
    parser.add_argument("--tasks", type=str,
                        default="evaluation/live_campaign/tasks.json",
                        help="Path to tasks JSON")
    args = parser.parse_args()

    tasks = load_ladder_tasks(args.tasks)
    if args.bucket:
        tasks = [t for t in tasks if getattr(t, "bucket", "") == args.bucket.upper()
                 or (hasattr(t, "id") and t.id.startswith(args.bucket.upper()))]

    print(f"\nLive Campaign: {len(tasks)} tasks")
    print(f"Provider: {args.provider} | Model: {args.model}")
    print(f"Delay: {args.delay}s\n")

    results = run_live_campaign(
        tasks, args.provider, args.model,
        base_url=args.base_url, delay=args.delay,
    )

    print()
    print(format_live_report(results))

    if args.save:
        Path(args.save).write_text(json.dumps(
            {"results": [r.model_dump() for r in results],
             "buckets": summarize_by_bucket(results)},
            indent=2, default=str,
        ))
        print(f"\nSaved to {args.save}")


if __name__ == "__main__":
    main()
