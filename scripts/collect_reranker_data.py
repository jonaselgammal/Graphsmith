#!/usr/bin/env python3
"""Collect reranker training data by running eval with full candidate traces.

Usage:
    python scripts/collect_reranker_data.py --runs 3 --output /tmp/reranker_data.jsonl
    python scripts/collect_reranker_data.py --runs 5 --provider openai --model llama-3.1-8b-instant --base-url https://api.groq.com/openai/v1
"""
import argparse
import json
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graphsmith.evaluation.planner_eval import EvalGoal, load_goals, evaluate_goal
from graphsmith.evaluation.reranker_dataset import CandidateRow, export_dataset
from graphsmith.evaluation.stability import classify_failure
from graphsmith.planner.ir_backend import IRPlannerBackend
from graphsmith.planner.ir_scorer import score_candidate
from graphsmith.registry.local import LocalRegistry


def collect_data(
    registry: LocalRegistry,
    backend: IRPlannerBackend,
    goals_dirs: list[str],
    *,
    runs: int = 1,
    delay: float = 5.0,
) -> list[CandidateRow]:
    """Run eval multiple times and collect candidate-level rows."""
    all_goals: list[EvalGoal] = []
    for d in goals_dirs:
        all_goals.extend(load_goals(d))

    rows: list[CandidateRow] = []

    for run_idx in range(runs):
        print(f"Run {run_idx + 1}/{runs}...")
        for i, eval_goal in enumerate(all_goals):
            if delay > 0 and i > 0:
                time.sleep(delay)

            result = evaluate_goal(eval_goal, registry, backend)
            passed = result.status == "pass"
            fc = classify_failure(result) if not passed else ""

            # Extract candidate-level data from backend
            for cand in backend.last_candidates:
                if cand.status != "compiled" or cand.ir is None:
                    continue

                skill_ids = [s.skill_id for s in cand.ir.steps]
                output_names = list(cand.ir.final_outputs.keys())
                is_winner = (cand.glue is not None and result.plan_json is not None
                             and cand.glue.graph.outputs == result.plan_json.get("graph", {}).get("outputs", {}))

                from graphsmith.evaluation.reranker_dataset import _build_row_from_candidate
                row = _build_row_from_candidate(
                    goal=eval_goal.goal,
                    run_index=run_idx,
                    candidate_index=cand.index,
                    skill_ids=skill_ids,
                    output_names=output_names,
                    step_count=len(cand.ir.steps),
                    score=cand.score.total if cand.score else 0.0,
                    penalties=cand.score.penalties if cand.score else [],
                    rewards=cand.score.rewards if cand.score else [],
                    passed_eval=passed if is_winner else False,
                    failure_class=fc if is_winner and not passed else "",
                )
                row.correct_skills_check = result.checks.correct_skills
                row.correct_outputs_check = result.checks.correct_outputs
                row.validates_check = result.checks.validates
                rows.append(row)

        print(f"  Collected {len(rows)} candidate rows so far")

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect reranker training data")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", default="/tmp/reranker_data.jsonl")
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--model", default="llama-3.1-8b-instant")
    parser.add_argument("--base-url", default="https://api.groq.com/openai/v1")
    parser.add_argument("--delay", type=float, default=5.0)
    parser.add_argument("--registry", default=None)
    parser.add_argument("--ir-candidates", type=int, default=3)
    args = parser.parse_args()

    from graphsmith.ops.providers import create_provider

    # Registry
    if args.registry:
        reg = LocalRegistry(args.registry)
    else:
        import tempfile, subprocess
        reg_dir = tempfile.mkdtemp()
        for d in sorted(Path("examples/skills").iterdir()):
            if d.is_dir():
                subprocess.run(
                    ["graphsmith", "publish", str(d), "--registry", reg_dir],
                    capture_output=True,
                )
        reg = LocalRegistry(reg_dir)

    provider = create_provider(args.provider, model=args.model, base_url=args.base_url)
    backend = IRPlannerBackend(
        provider, candidate_count=args.ir_candidates, use_decomposition=True,
    )

    goals_dirs = ["evaluation/goals", "evaluation/holdout_goals", "evaluation/challenge_goals"]
    rows = collect_data(reg, backend, goals_dirs, runs=args.runs, delay=args.delay)

    export_dataset(rows, args.output)
    print(f"\nExported {len(rows)} rows to {args.output}")

    # Quick stats
    passed = sum(1 for r in rows if r.passed_eval)
    print(f"  Passed: {passed}/{len(rows)} ({100*passed/len(rows):.0f}%)")


if __name__ == "__main__":
    main()
