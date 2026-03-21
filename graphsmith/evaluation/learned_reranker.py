"""Lightweight learned reranker prototype.

Trains a gradient boosted classifier on candidate features to predict
whether a candidate will pass eval. Can be compared against the
deterministic scorer offline.
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any

from graphsmith.evaluation.reranker_dataset import (
    FEATURE_NAMES,
    CandidateRow,
    rows_to_features,
)


class LearnedReranker:
    """Thin wrapper around a trained sklearn classifier."""

    def __init__(self, model: Any = None) -> None:
        self._model = model

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    def predict_score(self, row: CandidateRow) -> float:
        """Predict pass probability for a single candidate."""
        if self._model is None:
            return 0.0
        X, _ = rows_to_features([row])
        proba = self._model.predict_proba(X)
        return float(proba[0][1])  # probability of class 1 (pass)

    def predict_scores(self, rows: list[CandidateRow]) -> list[float]:
        """Predict pass probabilities for multiple candidates."""
        if self._model is None or not rows:
            return [0.0] * len(rows)
        X, _ = rows_to_features(rows)
        proba = self._model.predict_proba(X)
        return [float(p[1]) for p in proba]

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("wb") as f:
            pickle.dump(self._model, f)

    @classmethod
    def load(cls, path: str | Path) -> LearnedReranker:
        with Path(path).open("rb") as f:
            model = pickle.load(f)
        return cls(model=model)


def train_reranker(
    rows: list[CandidateRow],
    *,
    n_estimators: int = 50,
    max_depth: int = 3,
    random_state: int = 42,
) -> LearnedReranker:
    """Train a gradient boosted classifier from candidate rows."""
    from sklearn.ensemble import GradientBoostingClassifier

    X, y = rows_to_features(rows)
    if len(set(y)) < 2:
        # Need at least both classes; train on degenerate data
        clf = GradientBoostingClassifier(
            n_estimators=1, max_depth=1, random_state=random_state,
        )
        clf.fit(X, y)
        return LearnedReranker(model=clf)

    clf = GradientBoostingClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        random_state=random_state,
        min_samples_leaf=2,
    )
    clf.fit(X, y)
    return LearnedReranker(model=clf)


def evaluate_reranker(
    reranker: LearnedReranker,
    rows: list[CandidateRow],
) -> dict[str, Any]:
    """Evaluate learned reranker on a set of candidate rows.

    Returns accuracy, precision, recall, and ranking comparison.
    """
    if not rows:
        return {"error": "no rows"}

    X, y_true = rows_to_features(rows)
    scores = reranker.predict_scores(rows)

    # Pointwise accuracy
    y_pred = [1 if s > 0.5 else 0 for s in scores]
    correct = sum(1 for a, b in zip(y_true, y_pred) if a == b)
    accuracy = correct / len(y_true)

    tp = sum(1 for a, b in zip(y_true, y_pred) if a == 1 and b == 1)
    fp = sum(1 for a, b in zip(y_true, y_pred) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(y_true, y_pred) if a == 1 and b == 0)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    return {
        "total_rows": len(rows),
        "positive_rows": sum(y_true),
        "negative_rows": len(y_true) - sum(y_true),
        "accuracy": round(accuracy, 3),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
    }


def compare_scorers(
    rows: list[CandidateRow],
    reranker: LearnedReranker,
) -> dict[str, Any]:
    """Compare deterministic scorer vs learned reranker on ranking quality.

    Groups rows by goal, then checks which scorer picks the passing
    candidate (if one exists).
    """
    # Group by goal
    groups: dict[str, list[CandidateRow]] = {}
    for r in rows:
        groups.setdefault(r.goal, []).append(r)

    det_correct = 0
    learned_correct = 0
    both_correct = 0
    neither_correct = 0
    total_groups = 0

    for goal, group in groups.items():
        has_pass = any(r.passed_eval for r in group)
        if not has_pass or len(group) < 2:
            continue  # skip groups without contrast

        total_groups += 1

        # Deterministic: pick highest det_score
        det_best = max(group, key=lambda r: r.det_score)
        det_ok = det_best.passed_eval

        # Learned: pick highest predicted score
        learned_scores = reranker.predict_scores(group)
        learned_best_idx = max(range(len(group)), key=lambda i: learned_scores[i])
        learned_ok = group[learned_best_idx].passed_eval

        if det_ok and learned_ok:
            both_correct += 1
        elif det_ok:
            det_correct += 1
        elif learned_ok:
            learned_correct += 1
        else:
            neither_correct += 1

    return {
        "total_groups": total_groups,
        "det_only_correct": det_correct,
        "learned_only_correct": learned_correct,
        "both_correct": both_correct,
        "neither_correct": neither_correct,
        "det_accuracy": round((det_correct + both_correct) / total_groups, 3) if total_groups else 0.0,
        "learned_accuracy": round((learned_correct + both_correct) / total_groups, 3) if total_groups else 0.0,
    }


def feature_importance(reranker: LearnedReranker) -> list[tuple[str, float]]:
    """Get feature importances from the trained model."""
    if not reranker.is_trained:
        return []
    importances = reranker._model.feature_importances_
    paired = list(zip(FEATURE_NAMES, importances))
    return sorted(paired, key=lambda x: -x[1])
