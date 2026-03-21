"""Deterministic semantic scorer for IR candidates.

Scores a compiled IR candidate against the goal text using explicit
rule-based penalties and rewards. No LLM involvement.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from graphsmith.planner.decomposition import SemanticDecomposition
from graphsmith.planner.ir import PlanningIR


class ScoreBreakdown(BaseModel):
    """Detailed breakdown of a candidate's semantic score."""

    base_score: float = 100.0
    penalties: list[tuple[str, float]] = Field(default_factory=list)
    rewards: list[tuple[str, float]] = Field(default_factory=list)
    total: float = 0.0
    valid: bool = True


# ── Goal analysis ──────────────────────────────────────────────────

_FORMATTING_KEYWORDS = {
    "format", "list", "bullet", "header", "present", "readable",
    "table", "prefix", "nicely",
}

_GOAL_SKILL_MAP: list[tuple[set[str], str, str]] = [
    # (goal keywords, skill_id, label)
    ({"clean", "tidy", "normalize", "cleanup", "lowercase", "trim"}, "text.normalize.v1", "normalize"),
    ({"summarize", "summary", "condense", "brief"}, "text.summarize.v1", "summarize"),
    ({"keyword", "keywords", "topic", "topics", "extract"}, "text.extract_keywords.v1", "extract_keywords"),
    ({"capitalize", "title case", "capital letter"}, "text.title_case.v1", "title_case"),
    ({"sentiment", "analyze sentiment"}, "text.classify_sentiment.v1", "classify_sentiment"),
    ({"count", "how many words", "word count"}, "text.word_count.v1", "word_count"),
]

_FORMATTING_SKILLS = {
    "text.join_lines.v1",
    "text.prefix_lines.v1",
    "template.render",
}

_JSON_SKILLS = {
    "json.reshape.v1",
    "json.extract_field.v1",
    "json.pretty_print.v1",
    "json.parse",
}

# Expected output port names per skill
_SKILL_OUTPUT_PORTS: dict[str, str] = {
    "text.normalize.v1": "normalized",
    "text.summarize.v1": "summary",
    "text.extract_keywords.v1": "keywords",
    "text.title_case.v1": "titled",
    "text.classify_sentiment.v1": "sentiment",
    "text.word_count.v1": "count",
    "text.join_lines.v1": "joined",
    "text.prefix_lines.v1": "prefixed",
    "json.reshape.v1": "selected",
    "json.extract_field.v1": "value",
    "template.render": "rendered",
}


def _goal_words(goal: str) -> set[str]:
    """Extract lowercase words from goal text."""
    return set(re.findall(r"[a-z]+", goal.lower()))


def _goal_mentions_formatting(goal: str) -> bool:
    """Check if the goal explicitly requests formatting/presentation."""
    words = _goal_words(goal)
    return bool(words & _FORMATTING_KEYWORDS)


def _goal_mentions_json(goal: str) -> bool:
    words = _goal_words(goal)
    return bool(words & {"json", "reshape", "parse"})


def _expected_skills(goal: str) -> set[str]:
    """Determine which skills the goal implies."""
    goal_lower = goal.lower()
    expected: set[str] = set()
    for keywords, skill_id, _ in _GOAL_SKILL_MAP:
        if any(kw in goal_lower for kw in keywords):
            expected.add(skill_id)
    return expected


# ── Scorer ─────────────────────────────────────────────────────────


def score_candidate(
    ir: PlanningIR,
    goal: str,
    decomposition: SemanticDecomposition | None = None,
) -> ScoreBreakdown:
    """Score a compiled IR candidate against the goal.

    If a decomposition is provided, additional consistency checks are applied.

    Returns a ScoreBreakdown with base 100, penalties subtracted,
    rewards added.
    """
    breakdown = ScoreBreakdown(base_score=100.0)
    ir_skills = {step.skill_id for step in ir.steps}
    output_names = set(ir.final_outputs.keys())
    goal_lower = goal.lower()
    wants_formatting = _goal_mentions_formatting(goal)
    wants_json = _goal_mentions_json(goal)
    expected = _expected_skills(goal)

    # B1: Penalize unnecessary formatting
    formatting_in_plan = ir_skills & _FORMATTING_SKILLS
    if formatting_in_plan and not wants_formatting:
        penalty = 20.0 * len(formatting_in_plan)
        breakdown.penalties.append(
            (f"unnecessary_formatting: {', '.join(sorted(formatting_in_plan))}", penalty)
        )

    # B2: Reward required transformations
    for skill_id in expected:
        if skill_id in ir_skills:
            breakdown.rewards.append((f"has_required_skill: {skill_id}", 10.0))

    # B2b: Penalize missing required transformations
    for skill_id in expected:
        if skill_id not in ir_skills:
            breakdown.penalties.append((f"missing_required_skill: {skill_id}", 15.0))

    # B3: Penalize wrong skill family
    json_in_plan = ir_skills & _JSON_SKILLS
    if json_in_plan and not wants_json:
        penalty = 15.0 * len(json_in_plan)
        breakdown.penalties.append(
            (f"wrong_skill_family_json_for_text: {', '.join(sorted(json_in_plan))}", penalty)
        )

    text_skills = ir_skills - _JSON_SKILLS - _FORMATTING_SKILLS - {"skill.invoke"}
    if wants_json and not (ir_skills & _JSON_SKILLS) and not text_skills:
        breakdown.penalties.append(("no_json_skill_for_json_goal", 15.0))

    # B4: Output endpoint alignment
    for out_name, ref in ir.final_outputs.items():
        producing_step = None
        for step in ir.steps:
            if step.name == ref.step:
                producing_step = step
                break
        if producing_step:
            expected_port = _SKILL_OUTPUT_PORTS.get(producing_step.skill_id, "")
            if expected_port and ref.port == expected_port and out_name == expected_port:
                breakdown.rewards.append((f"correct_output_name: {out_name}", 5.0))
            elif expected_port and out_name != expected_port:
                breakdown.penalties.append(
                    (f"output_name_mismatch: '{out_name}' should be '{expected_port}'", 10.0)
                )

    # B5: Prefer minimal plans
    expected_step_count = len(expected)
    if wants_formatting:
        expected_step_count += 1
    actual_count = len(ir.steps)
    excess = max(0, actual_count - max(expected_step_count, 1))
    if excess > 0:
        breakdown.penalties.append((f"excess_steps: {excess} extra", 5.0 * excess))

    # B6: Decomposition consistency (if provided)
    if decomposition is not None:
        _score_decomposition_consistency(breakdown, ir, decomposition)

    # Calculate total
    total_penalties = sum(p for _, p in breakdown.penalties)
    total_rewards = sum(r for _, r in breakdown.rewards)
    breakdown.total = breakdown.base_score - total_penalties + total_rewards

    return breakdown


# ── Decomposition → skill mapping for consistency checks ──────────

_TRANSFORM_TO_SKILLS: dict[str, set[str]] = {
    "normalize": {"text.normalize.v1"},
    "summarize": {"text.summarize.v1"},
    "extract_keywords": {"text.extract_keywords.v1"},
    "title_case": {"text.title_case.v1"},
    "classify_sentiment": {"text.classify_sentiment.v1"},
    "word_count": {"text.word_count.v1"},
    "reshape_json": {"json.reshape.v1"},
    "extract_field": {"json.extract_field.v1"},
}

_PRESENTATION_SKILLS: dict[str, set[str]] = {
    "none": set(),
    "list": {"text.join_lines.v1"},
    "header": {"template.render", "text.prefix_lines.v1"},
    "template": {"template.render"},
}


def _score_decomposition_consistency(
    breakdown: ScoreBreakdown,
    ir: PlanningIR,
    decomp: SemanticDecomposition,
) -> None:
    """Add penalties/rewards for IR ↔ decomposition consistency."""
    ir_skills = {step.skill_id for step in ir.steps}
    output_names = set(ir.final_outputs.keys())

    # Check required content transforms are present
    for transform in decomp.content_transforms:
        required_skills = _TRANSFORM_TO_SKILLS.get(transform, set())
        if required_skills and not (ir_skills & required_skills):
            breakdown.penalties.append(
                (f"decomp_missing_transform: {transform}", 25.0)
            )
        elif required_skills and (ir_skills & required_skills):
            breakdown.rewards.append(
                (f"decomp_has_transform: {transform}", 8.0)
            )

    # Check presentation alignment
    if decomp.presentation == "none":
        formatting_in_plan = ir_skills & _FORMATTING_SKILLS
        if formatting_in_plan:
            breakdown.penalties.append(
                (f"decomp_unwanted_presentation: {', '.join(sorted(formatting_in_plan))}", 25.0)
            )
    else:
        expected_pres = _PRESENTATION_SKILLS.get(decomp.presentation, set())
        if expected_pres and not (ir_skills & expected_pres):
            breakdown.penalties.append(
                (f"decomp_missing_presentation: {decomp.presentation}", 20.0)
            )
        elif expected_pres and (ir_skills & expected_pres):
            breakdown.rewards.append(
                (f"decomp_correct_presentation: {decomp.presentation}", 8.0)
            )

    # Check final output names match decomposition
    if decomp.final_output_names:
        expected_outs = set(decomp.final_output_names)
        for name in expected_outs:
            if name in output_names:
                breakdown.rewards.append((f"decomp_output_match: {name}", 5.0))
            else:
                breakdown.penalties.append((f"decomp_output_missing: {name}", 15.0))
