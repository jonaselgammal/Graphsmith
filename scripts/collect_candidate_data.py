#!/usr/bin/env python3
"""Collect candidate-level reranker data with per-candidate eval labels.

Usage:
    python scripts/collect_candidate_data.py --runs 3
    python scripts/collect_candidate_data.py --runs 1 --provider anthropic --model claude-haiku-4-5-20251001
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graphsmith.evaluation.candidate_dataset import (
    CandidateGroup,
    CandidateSample,
    analyze_groups,
    build_group,
    build_sample,
    export_groups,
    export_samples,
    print_analysis,
)
from graphsmith.evaluation.planner_eval import EvalGoal, load_goals
from graphsmith.planner.candidates import retrieve_candidates
from graphsmith.planner.ir_backend import IRPlannerBackend
from graphsmith.planner.models import PlanRequest
from graphsmith.registry.local import LocalRegistry


def collect(
    registry: LocalRegistry,
    backend: IRPlannerBackend,
    goals_dirs: list[str],
    *,
    runs: int = 1,
    delay: float = 5.0,
) -> tuple[list[CandidateSample], list[CandidateGroup]]:
    all_goals: list[EvalGoal] = []
    for d in goals_dirs:
        all_goals.extend(load_goals(d))

    all_samples: list[CandidateSample] = []
    all_groups: list[CandidateGroup] = []

    for run_idx in range(runs):
        print(f"Run {run_idx + 1}/{runs} ({len(all_goals)} goals)...")
        for i, eval_goal in enumerate(all_goals):
            if delay > 0 and (i > 0 or run_idx > 0):
                time.sleep(delay)

            # Run the planner
            cands = retrieve_candidates(eval_goal.goal, registry)
            request = PlanRequest(goal=eval_goal.goal, candidates=cands)
            result = backend.compose(request)

            # Get decomposition
            decomp = None
            if backend.last_decomposition:
                decomp = backend.last_decomposition.model_dump()

            # Determine which candidate was selected
            selected_idx = -1
            if result.graph is not None:
                for c in backend.last_candidates:
                    if (c.status == "compiled" and c.glue is not None
                            and c.glue.graph.outputs == result.graph.graph.outputs):
                        selected_idx = c.index
                        break

            # Build samples for ALL candidates
            samples: list[CandidateSample] = []
            for c in backend.last_candidates:
                sample = build_sample(
                    c, eval_goal,
                    run_index=run_idx,
                    decomp=decomp,
                    was_selected=(c.index == selected_idx),
                )
                samples.append(sample)
                all_samples.append(sample)

            # Build group
            group = build_group(samples, selected_idx)
            all_groups.append(group)

        run_groups = all_groups[run_idx * len(all_goals):(run_idx + 1) * len(all_goals)]
        passed = sum(1 for g in run_groups if g.selected_passes)
        print(f"  Selected passes: {passed}/{len(all_goals)}")

    return all_samples, all_groups


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output-dir", default="/tmp/candidate_dataset")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model", default="llama-3.1-8b-instant")
    parser.add_argument("--base-url", default="https://api.groq.com/openai/v1")
    parser.add_argument("--delay", type=float, default=5.0)
    parser.add_argument("--ir-candidates", type=int, default=3)
    args = parser.parse_args()

    from graphsmith.ops.providers import create_provider

    # Registry
    import tempfile
    reg_dir = tempfile.mkdtemp()
    for d in sorted(Path("examples/skills").iterdir()):
        if d.is_dir():
            import subprocess
            subprocess.run(["graphsmith", "publish", str(d), "--registry", reg_dir],
                           capture_output=True)
    reg = LocalRegistry(reg_dir)

    provider = create_provider(args.provider, model=args.model, base_url=args.base_url)
    backend = IRPlannerBackend(
        provider, candidate_count=args.ir_candidates, use_decomposition=True,
    )

    goals_dirs = ["evaluation/goals", "evaluation/holdout_goals", "evaluation/challenge_goals"]
    samples, groups = collect(reg, backend, goals_dirs, runs=args.runs, delay=args.delay)

    # Export
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    export_samples(samples, out / "samples.jsonl")
    export_groups(groups, out / "groups.jsonl")

    print(f"\nExported {len(samples)} samples, {len(groups)} groups to {out}")

    # Analysis
    analysis = analyze_groups(groups)
    print()
    print(print_analysis(analysis))

    # Save analysis
    (out / "analysis.json").write_text(json.dumps(analysis, indent=2) + "\n")


if __name__ == "__main__":
    main()
