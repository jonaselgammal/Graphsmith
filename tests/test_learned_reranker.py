"""Tests for learned reranker dataset extraction, training, and evaluation."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

try:
    import sklearn  # noqa: F401
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

from graphsmith.evaluation.reranker_dataset import (
    FEATURE_NAMES,
    CandidateRow,
    export_dataset,
    extract_rows_from_diagnostics,
    load_dataset,
    rows_to_features,
)


# ── Dataset extraction ─────────────────────────────────────────────


class TestDatasetExtraction:
    def test_rows_from_diagnostics(self) -> None:
        diag = [
            {"goal": "Summarize this text", "status": "pass",
             "failure_type": "", "expected_in_shortlist": True,
             "checks": {"parsed": True, "has_graph": True, "validates": True,
                         "correct_skills": True, "correct_outputs": True,
                         "min_nodes_met": True, "no_holes": True}},
            {"goal": "Extract keywords", "status": "partial",
             "failure_type": "planner", "expected_in_shortlist": True,
             "checks": {"parsed": True, "has_graph": True, "validates": True,
                         "correct_skills": True, "correct_outputs": False,
                         "min_nodes_met": True, "no_holes": True}},
        ]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(diag, f)
            path = f.name

        rows = extract_rows_from_diagnostics(path)
        assert len(rows) == 2
        assert rows[0].passed_eval is True
        assert rows[1].passed_eval is False
        Path(path).unlink()

    def test_goal_features_extracted(self) -> None:
        diag = [
            {"goal": "Extract keywords and format as a list", "status": "pass",
             "failure_type": "", "expected_in_shortlist": True,
             "checks": {"parsed": True, "has_graph": True, "validates": True,
                         "correct_skills": True, "correct_outputs": True,
                         "min_nodes_met": True, "no_holes": True}},
        ]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(diag, f)
            path = f.name

        rows = extract_rows_from_diagnostics(path)
        r = rows[0]
        assert r.goal_mentions_keywords is True
        assert r.goal_mentions_format is True
        assert r.goal_mentions_json is False
        Path(path).unlink()


# ── Feature generation ─────────────────────────────────────────────


class TestFeatureGeneration:
    def test_rows_to_features_shape(self) -> None:
        rows = [
            CandidateRow(goal="test", step_count=2, passed_eval=True),
            CandidateRow(goal="test", step_count=1, passed_eval=False),
        ]
        X, y = rows_to_features(rows)
        assert len(X) == 2
        assert len(X[0]) == len(FEATURE_NAMES)
        assert y == [1, 0]

    def test_feature_names_count(self) -> None:
        assert len(FEATURE_NAMES) == 28

    def test_boolean_features_are_numeric(self) -> None:
        row = CandidateRow(
            goal="test",
            has_formatting_skill=True,
            has_normalize=False,
            goal_mentions_json=True,
        )
        X, _ = rows_to_features([row])
        # All values should be float
        for v in X[0]:
            assert isinstance(v, float)


# ── Dataset export/import ──────────────────────────────────────────


class TestDatasetExportImport:
    def test_roundtrip(self) -> None:
        rows = [
            CandidateRow(goal="g1", step_count=1, passed_eval=True, det_score=115.0),
            CandidateRow(goal="g2", step_count=2, passed_eval=False, failure_class="wrong_output_name"),
        ]
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        export_dataset(rows, path)
        loaded = load_dataset(path)

        assert len(loaded) == 2
        assert loaded[0].goal == "g1"
        assert loaded[0].det_score == 115.0
        assert loaded[1].failure_class == "wrong_output_name"
        Path(path).unlink()


# ── Learned reranker training ──────────────────────────────────────


@pytest.mark.skipif(not HAS_SKLEARN, reason="scikit-learn not installed")
class TestLearnedReranker:
    def _make_training_rows(self) -> list[CandidateRow]:
        """Create synthetic training data with clear signal."""
        rows = []
        # Pattern: formatting_skill + no goal_format → bad
        for i in range(20):
            rows.append(CandidateRow(
                goal=f"extract_keywords_{i}", step_count=1,
                has_extract_keywords=True, has_formatting_skill=False,
                goal_mentions_keywords=True, goal_mentions_format=False,
                det_score=115.0, passed_eval=True,
            ))
            rows.append(CandidateRow(
                goal=f"extract_keywords_{i}", step_count=2,
                has_extract_keywords=True, has_formatting_skill=True,
                goal_mentions_keywords=True, goal_mentions_format=False,
                det_score=80.0, passed_eval=False,
                failure_class="wrong_output_name",
            ))
        # Pattern: formatting_skill + goal_format → good
        for i in range(10):
            rows.append(CandidateRow(
                goal=f"format_keywords_{i}", step_count=2,
                has_extract_keywords=True, has_formatting_skill=True,
                goal_mentions_keywords=True, goal_mentions_format=True,
                det_score=115.0, passed_eval=True,
            ))
        return rows

    def test_training_smoke(self) -> None:
        """Reranker can be trained without errors."""
        from graphsmith.evaluation.learned_reranker import train_reranker
        rows = self._make_training_rows()
        reranker = train_reranker(rows)
        assert reranker.is_trained

    def test_prediction(self) -> None:
        from graphsmith.evaluation.learned_reranker import train_reranker
        rows = self._make_training_rows()
        reranker = train_reranker(rows)

        good = CandidateRow(
            goal="test", step_count=1,
            has_extract_keywords=True, has_formatting_skill=False,
            goal_mentions_keywords=True, goal_mentions_format=False,
            det_score=115.0,
        )
        bad = CandidateRow(
            goal="test", step_count=2,
            has_extract_keywords=True, has_formatting_skill=True,
            goal_mentions_keywords=True, goal_mentions_format=False,
            det_score=80.0,
        )
        score_good = reranker.predict_score(good)
        score_bad = reranker.predict_score(bad)
        assert score_good > score_bad

    def test_evaluate(self) -> None:
        from graphsmith.evaluation.learned_reranker import evaluate_reranker, train_reranker
        rows = self._make_training_rows()
        reranker = train_reranker(rows)
        result = evaluate_reranker(reranker, rows)
        assert "accuracy" in result
        assert result["accuracy"] > 0.5  # should be well above random

    def test_compare_scorers(self) -> None:
        from graphsmith.evaluation.learned_reranker import compare_scorers, train_reranker
        rows = self._make_training_rows()
        reranker = train_reranker(rows)
        comparison = compare_scorers(rows, reranker)
        assert "det_accuracy" in comparison
        assert "learned_accuracy" in comparison

    def test_feature_importance(self) -> None:
        from graphsmith.evaluation.learned_reranker import feature_importance, train_reranker
        rows = self._make_training_rows()
        reranker = train_reranker(rows)
        fi = feature_importance(reranker)
        assert len(fi) == len(FEATURE_NAMES)
        # Top feature should have non-zero importance
        assert fi[0][1] > 0

    def test_save_load_roundtrip(self) -> None:
        from graphsmith.evaluation.learned_reranker import train_reranker, LearnedReranker
        rows = self._make_training_rows()
        reranker = train_reranker(rows)

        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name

        reranker.save(path)
        loaded = LearnedReranker.load(path)
        assert loaded.is_trained

        row = CandidateRow(goal="test", step_count=1, det_score=100.0)
        assert abs(reranker.predict_score(row) - loaded.predict_score(row)) < 1e-6
        Path(path).unlink()


# ── No regression ──────────────────────────────────────────────────


class TestNoRegression:
    def test_existing_scorer_import(self) -> None:
        """Existing scorer still importable and functional."""
        from graphsmith.planner.ir_scorer import score_candidate
        from graphsmith.planner.ir import IRInput, IROutputRef, IRSource, IRStep, PlanningIR
        ir = PlanningIR(
            goal="test",
            inputs=[IRInput(name="text")],
            steps=[IRStep(name="e", skill_id="text.extract_keywords.v1",
                          sources={"text": IRSource(step="input", port="text")})],
            final_outputs={"keywords": IROutputRef(step="e", port="keywords")},
            effects=["llm_inference"],
        )
        score = score_candidate(ir, "extract keywords")
        assert score.total > 0
