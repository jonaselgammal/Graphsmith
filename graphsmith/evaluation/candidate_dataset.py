"""Candidate-level dataset for learned reranking.

Collects ALL IR candidates per goal/run with independent eval labels,
enabling contrast-based learning.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from graphsmith.evaluation.planner_eval import EvalChecks, EvalGoal
from graphsmith.exceptions import ValidationError
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.planner.ir_backend import CandidateResult
from graphsmith.planner.ir_scorer import ScoreBreakdown
from graphsmith.planner.models import GlueGraph
from graphsmith.validator import validate_skill_package


# ── Schema ─────────────────────────────────────────────────────────


class CandidateSample(BaseModel):
    """One candidate with full features and labels."""

    # Identity
    goal: str
    run_index: int = 0
    candidate_index: int = 0
    group_id: str = ""  # "{goal}::{run_index}" for grouping

    # Candidate structure
    step_count: int = 0
    skill_ids: list[str] = Field(default_factory=list)
    output_names: list[str] = Field(default_factory=list)
    node_ops: list[str] = Field(default_factory=list)

    # Skill presence features
    has_normalize: bool = False
    has_summarize: bool = False
    has_extract_keywords: bool = False
    has_title_case: bool = False
    has_sentiment: bool = False
    has_word_count: bool = False
    has_reshape: bool = False
    has_extract_field: bool = False
    has_join_lines: bool = False
    has_prefix_lines: bool = False
    has_template_render: bool = False

    # Goal features
    goal_mentions_format: bool = False
    goal_mentions_header: bool = False
    goal_mentions_json: bool = False
    goal_mentions_clean: bool = False
    goal_mentions_summarize: bool = False
    goal_mentions_keywords: bool = False
    goal_mentions_capitalize: bool = False
    goal_mentions_count: bool = False
    goal_mentions_sentiment: bool = False

    # Deterministic score
    det_score: float = 0.0
    det_penalty_total: float = 0.0
    det_reward_total: float = 0.0
    det_penalty_count: int = 0
    det_has_unnecessary_formatting: bool = False
    det_has_missing_skill: bool = False
    det_has_wrong_family: bool = False
    det_has_output_mismatch: bool = False
    det_has_excess_steps: bool = False
    det_has_decomp_unwanted: bool = False
    det_has_decomp_missing_transform: bool = False
    det_has_decomp_missing_presentation: bool = False

    # Decomposition
    decomp_content_transforms: list[str] = Field(default_factory=list)
    decomp_presentation: str = "none"
    decomp_output_names: list[str] = Field(default_factory=list)

    # Pointwise labels
    candidate_compiled: bool = False
    candidate_validates: bool = False
    would_pass_eval: bool = False
    failure_class: str = ""

    # Ranking labels
    was_selected: bool = False
    rank: int = 0  # 1 = best, 0 = unranked/invalid
    is_best: bool = False
    beats_selected: bool = False


class CandidateGroup(BaseModel):
    """All candidates for one (goal, run) pair."""

    goal: str
    run_index: int = 0
    group_id: str = ""
    candidates: list[CandidateSample] = Field(default_factory=list)
    selected_index: int = -1
    best_index: int = -1
    has_passing_candidate: bool = False
    selected_passes: bool = False
    oracle_passes: bool = False


# ── Labeling ───────────────────────────────────────────────────────


def label_candidate(
    cand: CandidateResult,
    eval_goal: EvalGoal,
) -> tuple[bool, bool, str]:
    """Evaluate a single candidate against the eval spec.

    Returns (validates, would_pass, failure_class).
    """
    if cand.status != "compiled" or cand.glue is None:
        return False, False, "invalid_candidate"

    # Validate
    validates = True
    try:
        pkg = glue_to_skill_package(cand.glue)
        validate_skill_package(pkg)
    except (ValidationError, Exception):
        validates = False

    if not validates:
        return False, False, "validation_error"

    # Check skills
    node_skills = set()
    for node in cand.glue.graph.nodes:
        sid = node.config.get("skill_id", "")
        if sid:
            node_skills.add(sid)

    correct_skills = True
    if eval_goal.expected_skills:
        correct_skills = all(s in node_skills for s in eval_goal.expected_skills)

    # Check outputs
    mapped_outputs = set(cand.glue.graph.outputs.keys())
    correct_outputs = True
    if eval_goal.acceptable_output_names:
        correct_outputs = all(
            any(name in mapped_outputs for name in alts)
            for alts in eval_goal.acceptable_output_names
        )
    elif eval_goal.expected_output_names:
        correct_outputs = all(
            name in mapped_outputs for name in eval_goal.expected_output_names
        )

    # Check min nodes
    min_nodes_met = len(cand.glue.graph.nodes) >= eval_goal.min_nodes

    would_pass = validates and correct_skills and correct_outputs and min_nodes_met

    if would_pass:
        return True, True, ""

    # Classify failure
    if not correct_skills and not correct_outputs:
        return True, False, "wrong_skill_and_output"
    if not correct_skills:
        return True, False, "wrong_skill_selection"
    if not correct_outputs:
        return True, False, "wrong_output_name"
    if not min_nodes_met:
        return True, False, "too_few_nodes"
    return True, False, "other"


_FORMAT_WORDS = {"format", "list", "bullet", "readable", "nicely", "present"}
_HEADER_WORDS = {"header", "prefix"}


def build_sample(
    cand: CandidateResult,
    eval_goal: EvalGoal,
    *,
    run_index: int = 0,
    decomp: dict[str, Any] | None = None,
    was_selected: bool = False,
) -> CandidateSample:
    """Build a fully labeled CandidateSample from a CandidateResult."""
    goal = eval_goal.goal
    goal_lower = goal.lower()
    goal_words = set(re.findall(r"[a-z]+", goal_lower))
    group_id = f"{goal}::{run_index}"

    # Structure
    skill_ids: list[str] = []
    output_names: list[str] = []
    node_ops: list[str] = []
    if cand.ir:
        skill_ids = [s.skill_id for s in cand.ir.steps]
        output_names = list(cand.ir.final_outputs.keys())
    if cand.glue:
        node_ops = [n.op for n in cand.glue.graph.nodes]

    skill_set = set(skill_ids)

    # Labels
    validates, would_pass, failure_class = label_candidate(cand, eval_goal)

    # Score breakdown
    det_score = cand.score.total if cand.score else 0.0
    penalty_total = sum(p for _, p in cand.score.penalties) if cand.score else 0.0
    reward_total = sum(r for _, r in cand.score.rewards) if cand.score else 0.0
    penalty_reasons = set()
    if cand.score:
        for reason, _ in cand.score.penalties:
            penalty_reasons.add(reason)

    # Decomposition
    decomp_ct = decomp.get("content_transforms", []) if decomp else []
    decomp_pres = decomp.get("presentation", "none") if decomp else "none"
    decomp_outs = decomp.get("final_output_names", []) if decomp else []

    return CandidateSample(
        goal=goal,
        run_index=run_index,
        candidate_index=cand.index,
        group_id=group_id,
        step_count=len(skill_ids),
        skill_ids=skill_ids,
        output_names=output_names,
        node_ops=node_ops,
        has_normalize="text.normalize.v1" in skill_set,
        has_summarize="text.summarize.v1" in skill_set,
        has_extract_keywords="text.extract_keywords.v1" in skill_set,
        has_title_case="text.title_case.v1" in skill_set,
        has_sentiment="text.classify_sentiment.v1" in skill_set,
        has_word_count="text.word_count.v1" in skill_set,
        has_reshape="json.reshape.v1" in skill_set,
        has_extract_field="json.extract_field.v1" in skill_set,
        has_join_lines="text.join_lines.v1" in skill_set,
        has_prefix_lines="text.prefix_lines.v1" in skill_set,
        has_template_render="template.render" in skill_set,
        goal_mentions_format=bool(goal_words & _FORMAT_WORDS),
        goal_mentions_header=bool(goal_words & _HEADER_WORDS),
        goal_mentions_json="json" in goal_lower,
        goal_mentions_clean=any(w in goal_lower for w in ["clean", "tidy", "normalize", "lowercase", "trim"]),
        goal_mentions_summarize=any(w in goal_lower for w in ["summarize", "summary", "condense", "brief"]),
        goal_mentions_keywords=any(w in goal_lower for w in ["keyword", "topic"]),
        goal_mentions_capitalize=any(w in goal_lower for w in ["capitalize", "capital"]),
        goal_mentions_count=any(w in goal_lower for w in ["count", "how many"]),
        goal_mentions_sentiment="sentiment" in goal_lower,
        det_score=det_score,
        det_penalty_total=penalty_total,
        det_reward_total=reward_total,
        det_penalty_count=len(cand.score.penalties) if cand.score else 0,
        det_has_unnecessary_formatting=any("unnecessary_formatting" in r for r in penalty_reasons),
        det_has_missing_skill=any("missing_required_skill" in r for r in penalty_reasons),
        det_has_wrong_family=any("wrong_skill_family" in r for r in penalty_reasons),
        det_has_output_mismatch=any("output_name_mismatch" in r for r in penalty_reasons),
        det_has_excess_steps=any("excess_steps" in r for r in penalty_reasons),
        det_has_decomp_unwanted=any("decomp_unwanted" in r for r in penalty_reasons),
        det_has_decomp_missing_transform=any("decomp_missing_transform" in r for r in penalty_reasons),
        det_has_decomp_missing_presentation=any("decomp_missing_presentation" in r for r in penalty_reasons),
        decomp_content_transforms=decomp_ct,
        decomp_presentation=decomp_pres,
        decomp_output_names=decomp_outs,
        candidate_compiled=(cand.status == "compiled"),
        candidate_validates=validates,
        would_pass_eval=would_pass,
        failure_class=failure_class,
        was_selected=was_selected,
    )


def build_group(
    samples: list[CandidateSample],
    selected_index: int,
) -> CandidateGroup:
    """Build a CandidateGroup with ranking labels assigned."""
    if not samples:
        return CandidateGroup(goal="", group_id="")

    goal = samples[0].goal
    run_index = samples[0].run_index
    group_id = samples[0].group_id

    # Determine best: passing > non-passing, then highest det_score
    passing = [(i, s) for i, s in enumerate(samples) if s.would_pass_eval]
    if passing:
        best_idx = max(passing, key=lambda x: x[1].det_score)[0]
    else:
        compiled = [(i, s) for i, s in enumerate(samples) if s.candidate_compiled]
        best_idx = max(compiled, key=lambda x: x[1].det_score)[0] if compiled else 0

    # Assign ranks: sort by (would_pass desc, det_score desc)
    ranked = sorted(
        range(len(samples)),
        key=lambda i: (samples[i].would_pass_eval, samples[i].det_score),
        reverse=True,
    )
    for rank_pos, idx in enumerate(ranked):
        samples[idx].rank = rank_pos + 1
        samples[idx].is_best = (idx == best_idx)
        samples[idx].beats_selected = (
            samples[idx].would_pass_eval and not samples[selected_index].would_pass_eval
        ) if 0 <= selected_index < len(samples) else False

    has_passing = any(s.would_pass_eval for s in samples)
    selected_passes = samples[selected_index].would_pass_eval if 0 <= selected_index < len(samples) else False
    oracle_passes = has_passing

    return CandidateGroup(
        goal=goal,
        run_index=run_index,
        group_id=group_id,
        candidates=samples,
        selected_index=selected_index,
        best_index=best_idx,
        has_passing_candidate=has_passing,
        selected_passes=selected_passes,
        oracle_passes=oracle_passes,
    )


# ── Export/import ──────────────────────────────────────────────────


def export_samples(samples: list[CandidateSample], path: str | Path) -> None:
    """Export pointwise samples as JSONL."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s.model_dump()) + "\n")


def load_samples(path: str | Path) -> list[CandidateSample]:
    """Load pointwise samples from JSONL."""
    samples: list[CandidateSample] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            samples.append(CandidateSample.model_validate(json.loads(line)))
    return samples


def export_groups(groups: list[CandidateGroup], path: str | Path) -> None:
    """Export grouped ranking data as JSONL (one group per line)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for g in groups:
            f.write(json.dumps(g.model_dump()) + "\n")


def load_groups(path: str | Path) -> list[CandidateGroup]:
    """Load grouped ranking data from JSONL."""
    groups: list[CandidateGroup] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            groups.append(CandidateGroup.model_validate(json.loads(line)))
    return groups


# ── Analysis ───────────────────────────────────────────────────────


def analyze_groups(groups: list[CandidateGroup]) -> dict[str, Any]:
    """Compute reranking headroom analysis from candidate groups."""
    total = len(groups)
    if total == 0:
        return {"error": "no groups"}

    has_passing = sum(1 for g in groups if g.has_passing_candidate)
    selected_passes = sum(1 for g in groups if g.selected_passes)
    oracle_passes = sum(1 for g in groups if g.oracle_passes)
    better_available = sum(
        1 for g in groups
        if g.oracle_passes and not g.selected_passes
    )

    # Failure class distribution among non-passing selected candidates
    failure_classes: dict[str, int] = {}
    for g in groups:
        if not g.selected_passes and 0 <= g.selected_index < len(g.candidates):
            fc = g.candidates[g.selected_index].failure_class
            failure_classes[fc] = failure_classes.get(fc, 0) + 1

    # Per-candidate diversity
    total_candidates = sum(len(g.candidates) for g in groups)
    total_passing_candidates = sum(
        sum(1 for c in g.candidates if c.would_pass_eval)
        for g in groups
    )

    return {
        "total_groups": total,
        "has_passing_candidate": has_passing,
        "selected_passes": selected_passes,
        "oracle_passes": oracle_passes,
        "selected_pass_rate": round(selected_passes / total, 3),
        "oracle_pass_rate": round(oracle_passes / total, 3),
        "reranking_headroom": oracle_passes - selected_passes,
        "better_available": better_available,
        "total_candidates": total_candidates,
        "total_passing_candidates": total_passing_candidates,
        "candidate_pass_rate": round(total_passing_candidates / total_candidates, 3) if total_candidates else 0,
        "failure_classes": failure_classes,
    }


def print_analysis(analysis: dict[str, Any]) -> str:
    """Format analysis as human-readable text."""
    lines = [
        "Reranking Headroom Analysis",
        "=" * 50,
        f"  Total groups:            {analysis['total_groups']}",
        f"  Has passing candidate:   {analysis['has_passing_candidate']}",
        f"  Selected passes:         {analysis['selected_passes']} ({analysis['selected_pass_rate']:.0%})",
        f"  Oracle passes:           {analysis['oracle_passes']} ({analysis['oracle_pass_rate']:.0%})",
        f"  Reranking headroom:      {analysis['reranking_headroom']} goals",
        f"  Better available:        {analysis['better_available']} goals",
        "",
        f"  Total candidates:        {analysis['total_candidates']}",
        f"  Passing candidates:      {analysis['total_passing_candidates']} ({analysis['candidate_pass_rate']:.0%})",
        "",
    ]
    fcs = analysis.get("failure_classes", {})
    if fcs:
        lines.append("  Failure classes (selected non-passing):")
        for fc, count in sorted(fcs.items(), key=lambda x: -x[1]):
            lines.append(f"    {count:3d}x  {fc}")
    return "\n".join(lines)
