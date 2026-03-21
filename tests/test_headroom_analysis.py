"""Tests for weak-model headroom analysis."""
from __future__ import annotations

import pytest

from graphsmith.evaluation.candidate_dataset import (
    CandidateGroup,
    CandidateSample,
    analyze_groups,
)


def _sample(goal: str, passes: bool, score: float = 100.0, selected: bool = False) -> CandidateSample:
    return CandidateSample(
        goal=goal, would_pass_eval=passes, det_score=score,
        was_selected=selected, candidate_compiled=True, candidate_validates=True,
        failure_class="" if passes else "wrong_output_name",
    )


def _group(goal: str, candidates: list[CandidateSample], selected_idx: int) -> CandidateGroup:
    has_pass = any(c.would_pass_eval for c in candidates)
    sel_passes = candidates[selected_idx].would_pass_eval if 0 <= selected_idx < len(candidates) else False
    return CandidateGroup(
        goal=goal, candidates=candidates,
        selected_index=selected_idx,
        has_passing_candidate=has_pass,
        selected_passes=sel_passes,
        oracle_passes=has_pass,
    )


class TestOracleComputation:
    def test_oracle_finds_passing_when_selected_fails(self) -> None:
        """Oracle should find the passing candidate even if scorer picked wrong."""
        groups = [
            _group("g1", [
                _sample("g1", passes=False, score=110, selected=True),
                _sample("g1", passes=True, score=90),
                _sample("g1", passes=False, score=80),
            ], selected_idx=0),
        ]
        analysis = analyze_groups(groups)
        assert analysis["selected_passes"] == 0
        assert analysis["oracle_passes"] == 1
        assert analysis["reranking_headroom"] == 1

    def test_no_headroom_when_selected_passes(self) -> None:
        groups = [
            _group("g1", [
                _sample("g1", passes=True, score=115, selected=True),
                _sample("g1", passes=False, score=80),
            ], selected_idx=0),
        ]
        analysis = analyze_groups(groups)
        assert analysis["reranking_headroom"] == 0

    def test_no_headroom_when_all_fail(self) -> None:
        groups = [
            _group("g1", [
                _sample("g1", passes=False, score=100, selected=True),
                _sample("g1", passes=False, score=90),
            ], selected_idx=0),
        ]
        analysis = analyze_groups(groups)
        assert analysis["reranking_headroom"] == 0
        assert analysis["oracle_passes"] == 0

    def test_multiple_groups_headroom(self) -> None:
        groups = [
            # g1: selected passes
            _group("g1", [
                _sample("g1", passes=True, score=115, selected=True),
                _sample("g1", passes=True, score=110),
            ], selected_idx=0),
            # g2: selected fails, better exists
            _group("g2", [
                _sample("g2", passes=False, score=100, selected=True),
                _sample("g2", passes=True, score=90),
            ], selected_idx=0),
            # g3: all fail
            _group("g3", [
                _sample("g3", passes=False, score=100, selected=True),
                _sample("g3", passes=False, score=80),
            ], selected_idx=0),
        ]
        analysis = analyze_groups(groups)
        assert analysis["total_groups"] == 3
        assert analysis["selected_passes"] == 1
        assert analysis["oracle_passes"] == 2
        assert analysis["reranking_headroom"] == 1
        assert analysis["better_available"] == 1

    def test_candidate_pass_rate(self) -> None:
        groups = [
            _group("g1", [
                _sample("g1", passes=True),
                _sample("g1", passes=True),
                _sample("g1", passes=False),
            ], selected_idx=0),
        ]
        analysis = analyze_groups(groups)
        assert analysis["total_candidates"] == 3
        assert analysis["total_passing_candidates"] == 2
        assert abs(analysis["candidate_pass_rate"] - 0.667) < 0.01

    def test_failure_class_distribution(self) -> None:
        groups = [
            _group("g1", [
                _sample("g1", passes=False, selected=True),
            ], selected_idx=0),
        ]
        # The failure_class comes from the selected candidate
        groups[0].candidates[0].failure_class = "wrong_output_name"
        analysis = analyze_groups(groups)
        assert analysis["failure_classes"] == {"wrong_output_name": 1}
