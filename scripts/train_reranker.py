#!/usr/bin/env python3
"""Train and evaluate learned reranker from collected data.

Usage:
    python scripts/train_reranker.py /tmp/reranker_data.jsonl
    python scripts/train_reranker.py /tmp/reranker_data.jsonl --save-model /tmp/reranker.pkl
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graphsmith.evaluation.reranker_dataset import load_dataset, rows_to_features
from graphsmith.evaluation.learned_reranker import (
    train_reranker,
    evaluate_reranker,
    compare_scorers,
    feature_importance,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate learned reranker")
    parser.add_argument("data", help="JSONL dataset path")
    parser.add_argument("--save-model", default=None, help="Save trained model to path")
    parser.add_argument("--test-split", type=float, default=0.3, help="Test split ratio")
    args = parser.parse_args()

    rows = load_dataset(args.data)
    print(f"Loaded {len(rows)} candidate rows")
    passed = sum(1 for r in rows if r.passed_eval)
    print(f"  Passed: {passed} ({100*passed/len(rows):.0f}%)")
    print(f"  Failed: {len(rows)-passed} ({100*(len(rows)-passed)/len(rows):.0f}%)")

    # Split by goal to avoid leakage
    goals = sorted(set(r.goal for r in rows))
    split_idx = max(1, int(len(goals) * (1 - args.test_split)))
    train_goals = set(goals[:split_idx])
    test_goals = set(goals[split_idx:])

    train_rows = [r for r in rows if r.goal in train_goals]
    test_rows = [r for r in rows if r.goal in test_goals]

    print(f"\nSplit: {len(train_goals)} train goals, {len(test_goals)} test goals")
    print(f"  Train rows: {len(train_rows)}")
    print(f"  Test rows: {len(test_rows)}")

    # Train
    print("\nTraining reranker...")
    reranker = train_reranker(train_rows)

    # Evaluate
    print("\n=== TRAIN SET ===")
    train_eval = evaluate_reranker(reranker, train_rows)
    print(json.dumps(train_eval, indent=2))

    print("\n=== TEST SET ===")
    test_eval = evaluate_reranker(reranker, test_rows)
    print(json.dumps(test_eval, indent=2))

    # Compare with deterministic scorer
    print("\n=== RANKING COMPARISON (test set) ===")
    comparison = compare_scorers(test_rows, reranker)
    print(json.dumps(comparison, indent=2))

    # Feature importance
    print("\n=== TOP FEATURES ===")
    fi = feature_importance(reranker)
    for name, importance in fi[:10]:
        print(f"  {importance:.3f}  {name}")

    # Save model
    if args.save_model:
        reranker.save(args.save_model)
        print(f"\nModel saved to {args.save_model}")


if __name__ == "__main__":
    main()
