"""Dataset extraction for learned reranker from eval diagnostics.

Generates training examples by re-running the deterministic scorer on
each goal with synthetic candidate variations, labeled by whether they
would pass the eval checks.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CandidateRow(BaseModel):
    """One training row for the learned reranker."""

    # Identity
    goal: str
    run_index: int = 0
    candidate_index: int = 0

    # Features
    step_count: int = 0
    skill_ids: list[str] = Field(default_factory=list)
    output_names: list[str] = Field(default_factory=list)
    has_formatting_skill: bool = False
    has_json_skill: bool = False
    has_normalize: bool = False
    has_summarize: bool = False
    has_extract_keywords: bool = False
    has_title_case: bool = False
    has_sentiment: bool = False
    has_word_count: bool = False
    has_reshape: bool = False
    has_extract_field: bool = False

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

    # Deterministic score components
    det_score: float = 0.0
    det_penalty_count: int = 0
    det_reward_count: int = 0
    det_has_unnecessary_formatting: bool = False
    det_has_missing_skill: bool = False
    det_has_wrong_family: bool = False
    det_has_output_mismatch: bool = False
    det_has_excess_steps: bool = False

    # Decomposition alignment
    decomp_transforms_matched: int = 0
    decomp_transforms_missing: int = 0
    decomp_presentation_correct: bool = False
    decomp_outputs_matched: int = 0
    decomp_outputs_missing: int = 0

    # Label
    passed_eval: bool = False
    failure_class: str = ""

    # Eval context
    correct_skills_check: bool = False
    correct_outputs_check: bool = False
    validates_check: bool = False


_FORMATTING_SKILLS = {"text.join_lines.v1", "text.prefix_lines.v1", "template.render"}
_JSON_SKILLS = {"json.reshape.v1", "json.extract_field.v1", "json.pretty_print.v1"}
_FORMAT_WORDS = {"format", "list", "bullet", "readable", "nicely", "present"}
_HEADER_WORDS = {"header", "prefix"}


def extract_rows_from_diagnostics(
    diag_path: str | Path,
    *,
    run_index: int = 0,
) -> list[CandidateRow]:
    """Extract candidate rows from a diagnostics JSON file.

    Each eval result becomes one row (the winning candidate).
    """
    data = json.loads(Path(diag_path).read_text(encoding="utf-8"))
    rows: list[CandidateRow] = []

    for d in data:
        goal = d["goal"]
        status = d["status"]
        checks = d.get("checks", {})
        retrieval = d.get("retrieval", {})

        # Build skill/output info from the plan if available
        # (diagnostics don't store full candidate data, just the winner)
        skill_ids: list[str] = []
        output_names: list[str] = []

        # We need to infer from the checks and available data
        row = CandidateRow(
            goal=goal,
            run_index=run_index,
            candidate_index=0,
            passed_eval=(status == "pass"),
            failure_class=d.get("failure_type", ""),
            correct_skills_check=checks.get("correct_skills", False),
            correct_outputs_check=checks.get("correct_outputs", False),
            validates_check=checks.get("validates", False),
        )

        # Goal features
        goal_lower = goal.lower()
        goal_words = set(re.findall(r"[a-z]+", goal_lower))
        row.goal_mentions_format = bool(goal_words & _FORMAT_WORDS)
        row.goal_mentions_header = bool(goal_words & _HEADER_WORDS)
        row.goal_mentions_json = "json" in goal_lower
        row.goal_mentions_clean = any(w in goal_lower for w in ["clean", "tidy", "normalize", "lowercase", "trim"])
        row.goal_mentions_summarize = any(w in goal_lower for w in ["summarize", "summary", "condense", "brief"])
        row.goal_mentions_keywords = any(w in goal_lower for w in ["keyword", "topic", "extract"])
        row.goal_mentions_capitalize = any(w in goal_lower for w in ["capitalize", "capital", "title case"])
        row.goal_mentions_count = any(w in goal_lower for w in ["count", "how many"])
        row.goal_mentions_sentiment = "sentiment" in goal_lower

        rows.append(row)

    return rows


def extract_rows_from_traces(traces: list[dict[str, Any]]) -> list[CandidateRow]:
    """Extract candidate rows from full trace records (JSONL loaded)."""
    rows: list[CandidateRow] = []

    for trace in traces:
        goal = trace["goal"]
        passed = trace.get("status") == "pass"
        failure_class = trace.get("failure_class", "")

        for cand in trace.get("candidates", []):
            if cand.get("status") != "compiled":
                continue

            steps = cand.get("steps", [])
            outputs = cand.get("final_outputs", {})
            skill_ids = [s[1] if isinstance(s, (list, tuple)) else s for s in steps]
            output_names = list(outputs.keys()) if isinstance(outputs, dict) else []

            # Determine if this candidate was the winner
            is_winner = cand.get("selected", False)
            cand_passed = passed if is_winner else False

            row = _build_row_from_candidate(
                goal=goal,
                run_index=trace.get("run_index", 0),
                candidate_index=cand.get("index", 0),
                skill_ids=skill_ids,
                output_names=output_names,
                step_count=len(steps),
                score=cand.get("score", 0.0),
                penalties=cand.get("penalties", []),
                rewards=cand.get("rewards", []),
                passed_eval=cand_passed,
                failure_class=failure_class if not cand_passed else "",
            )
            rows.append(row)

    return rows


def _build_row_from_candidate(
    *,
    goal: str,
    run_index: int,
    candidate_index: int,
    skill_ids: list[str],
    output_names: list[str],
    step_count: int,
    score: float,
    penalties: list,
    rewards: list,
    passed_eval: bool,
    failure_class: str,
) -> CandidateRow:
    """Build a CandidateRow from candidate data."""
    skill_set = set(skill_ids)
    goal_lower = goal.lower()
    goal_words = set(re.findall(r"[a-z]+", goal_lower))

    # Parse penalty/reward reasons
    penalty_reasons = set()
    for item in penalties:
        reason = item[0] if isinstance(item, (list, tuple)) else str(item)
        penalty_reasons.add(reason)

    row = CandidateRow(
        goal=goal,
        run_index=run_index,
        candidate_index=candidate_index,
        step_count=step_count,
        skill_ids=skill_ids,
        output_names=output_names,
        has_formatting_skill=bool(skill_set & _FORMATTING_SKILLS),
        has_json_skill=bool(skill_set & _JSON_SKILLS),
        has_normalize="text.normalize.v1" in skill_set,
        has_summarize="text.summarize.v1" in skill_set,
        has_extract_keywords="text.extract_keywords.v1" in skill_set,
        has_title_case="text.title_case.v1" in skill_set,
        has_sentiment="text.classify_sentiment.v1" in skill_set,
        has_word_count="text.word_count.v1" in skill_set,
        has_reshape="json.reshape.v1" in skill_set,
        has_extract_field="json.extract_field.v1" in skill_set,
        goal_mentions_format=bool(goal_words & _FORMAT_WORDS),
        goal_mentions_header=bool(goal_words & _HEADER_WORDS),
        goal_mentions_json="json" in goal_lower,
        goal_mentions_clean=any(w in goal_lower for w in ["clean", "tidy", "normalize", "lowercase", "trim"]),
        goal_mentions_summarize=any(w in goal_lower for w in ["summarize", "summary", "condense", "brief"]),
        goal_mentions_keywords=any(w in goal_lower for w in ["keyword", "topic", "extract"]),
        goal_mentions_capitalize=any(w in goal_lower for w in ["capitalize", "capital", "title case"]),
        goal_mentions_count=any(w in goal_lower for w in ["count", "how many"]),
        goal_mentions_sentiment="sentiment" in goal_lower,
        det_score=score,
        det_penalty_count=len(penalties),
        det_reward_count=len(rewards),
        det_has_unnecessary_formatting=any("unnecessary_formatting" in str(r) for r in penalty_reasons),
        det_has_missing_skill=any("missing_required_skill" in str(r) for r in penalty_reasons),
        det_has_wrong_family=any("wrong_skill_family" in str(r) for r in penalty_reasons),
        det_has_output_mismatch=any("output_name_mismatch" in str(r) for r in penalty_reasons),
        det_has_excess_steps=any("excess_steps" in str(r) for r in penalty_reasons),
        passed_eval=passed_eval,
        failure_class=failure_class,
    )
    return row


def rows_to_features(rows: list[CandidateRow]) -> tuple[list[list[float]], list[int]]:
    """Convert rows to numeric feature matrix + labels for sklearn."""
    X: list[list[float]] = []
    y: list[int] = []
    for r in rows:
        features = [
            float(r.step_count),
            float(r.has_formatting_skill),
            float(r.has_json_skill),
            float(r.has_normalize),
            float(r.has_summarize),
            float(r.has_extract_keywords),
            float(r.has_title_case),
            float(r.has_sentiment),
            float(r.has_word_count),
            float(r.has_reshape),
            float(r.has_extract_field),
            float(r.goal_mentions_format),
            float(r.goal_mentions_header),
            float(r.goal_mentions_json),
            float(r.goal_mentions_clean),
            float(r.goal_mentions_summarize),
            float(r.goal_mentions_keywords),
            float(r.goal_mentions_capitalize),
            float(r.goal_mentions_count),
            float(r.goal_mentions_sentiment),
            r.det_score,
            float(r.det_penalty_count),
            float(r.det_reward_count),
            float(r.det_has_unnecessary_formatting),
            float(r.det_has_missing_skill),
            float(r.det_has_wrong_family),
            float(r.det_has_output_mismatch),
            float(r.det_has_excess_steps),
        ]
        X.append(features)
        y.append(1 if r.passed_eval else 0)
    return X, y


FEATURE_NAMES = [
    "step_count", "has_formatting_skill", "has_json_skill",
    "has_normalize", "has_summarize", "has_extract_keywords",
    "has_title_case", "has_sentiment", "has_word_count",
    "has_reshape", "has_extract_field",
    "goal_mentions_format", "goal_mentions_header", "goal_mentions_json",
    "goal_mentions_clean", "goal_mentions_summarize", "goal_mentions_keywords",
    "goal_mentions_capitalize", "goal_mentions_count", "goal_mentions_sentiment",
    "det_score", "det_penalty_count", "det_reward_count",
    "det_has_unnecessary_formatting", "det_has_missing_skill",
    "det_has_wrong_family", "det_has_output_mismatch", "det_has_excess_steps",
]


def export_dataset(rows: list[CandidateRow], path: str | Path) -> None:
    """Export dataset as JSONL."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r.model_dump()) + "\n")


def load_dataset(path: str | Path) -> list[CandidateRow]:
    """Load dataset from JSONL."""
    rows: list[CandidateRow] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(CandidateRow.model_validate(json.loads(line)))
    return rows
