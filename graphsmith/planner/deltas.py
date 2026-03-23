"""Plan deltas — semantic edits for interactive plan refinement.

A PlanDelta represents a user's requested change to a plan.
Deltas are extracted from natural language and applied by replanning
with explicit constraints.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from graphsmith.planner.models import GlueGraph


# ── Delta model ──────────────────────────────────────────────────


class PlanDelta(BaseModel):
    """A structured semantic edit to a plan."""

    kind: str  # add_step, remove_step, replace_step, add_output, remove_output,
               # require_skill, forbid_skill, replace_presentation
    target: str = ""       # skill_id, output name, or step name
    replacement: str = ""  # for replace operations
    reason: str = ""       # human-readable explanation


class RefinementRequest(BaseModel):
    """Parsed refinement: one or more deltas from a user request."""

    raw_request: str
    deltas: list[PlanDelta] = Field(default_factory=list)
    modified_goal: str = ""  # the original goal amended with constraints


# ── Delta extraction ─────────────────────────────────────────────

# Keyword patterns for deterministic delta extraction.
# Each pattern: (regex, delta_kind, target_group, replacement_group)

_PATTERNS: list[tuple[str, str, int, int]] = [
    # Add output
    (r"(?:also\s+)?keep\s+(?:the\s+)?(\w+)(?:\s+(?:text|output))?", "add_output", 1, 0),
    (r"also\s+(?:output|return|include)\s+(?:the\s+)?(\w+)", "add_output", 1, 0),
    # Remove step / forbid skill
    (r"(?:don'?t|do\s+not|remove|skip|drop)\s+(?:the\s+)?(\w+)(?:\s+step)?", "forbid_skill", 1, 0),
    (r"(?:don'?t|do\s+not)\s+(\w+)(?:\s+(?:it|the text|this))?", "forbid_skill", 1, 0),
    # Add step
    (r"(?:also|then|and)\s+(\w+)\s+(?:after|before|the\s+(?:text|result))", "add_step", 1, 0),
    (r"add\s+(\w+)\s+(?:after|before|step)", "add_step", 1, 0),
    # Replace presentation
    (r"(?:replace|change|switch)\s+(?:the\s+)?(?:list|formatting)\s+(?:with|to)\s+(?:a\s+)?(\w+)", "replace_presentation", 1, 0),
    (r"(?:use|format\s+(?:as|with))\s+(?:a\s+)?(\w+)\s+(?:instead|format)", "replace_presentation", 1, 0),
    # Require skill
    (r"(?:use|require|include)\s+(\w+[\w.]*\.v\d+)", "require_skill", 1, 0),
    (r"(?:just|only)\s+(\w+)\s+(?:keywords?|text|it)", "require_skill", 1, 0),
]

# Skill name resolution: short name → likely skill_id
_SKILL_HINTS: dict[str, str] = {
    "normalize": "text.normalize.v1",
    "summarize": "text.summarize.v1",
    "keywords": "text.extract_keywords.v1",
    "extract": "text.extract_keywords.v1",
    "uppercase": "text.uppercase.v1",
    "lowercase": "text.lowercase.v1",
    "trim": "text.trim.v1",
    "title": "text.title_case.v1",
    "capitalize": "text.title_case.v1",
    "count": "text.word_count.v1",
    "join": "text.join_lines.v1",
    "prefix": "text.prefix_lines.v1",
    "sentiment": "text.classify_sentiment.v1",
    "header": "template.render",
    "add": "math.add.v1",
    "subtract": "math.subtract.v1",
    "multiply": "math.multiply.v1",
    "divide": "math.divide.v1",
    "mean": "math.mean.v1",
    "median": "math.median.v1",
    "min": "math.min.v1",
    "max": "math.max.v1",
}

# Output name hints
_OUTPUT_HINTS: dict[str, str] = {
    "normalized": "normalized",
    "summary": "summary",
    "keywords": "keywords",
    "joined": "joined",
    "count": "count",
    "result": "result",
    "uppercased": "uppercased",
    "titled": "titled",
    "trimmed": "trimmed",
}


def extract_deltas(request: str, current_plan: GlueGraph | None = None) -> RefinementRequest:
    """Extract structured deltas from a natural language refinement request."""
    request_lower = request.lower().strip()
    deltas: list[PlanDelta] = []

    for pattern, kind, target_grp, repl_grp in _PATTERNS:
        match = re.search(pattern, request_lower)
        if match:
            target = match.group(target_grp) if target_grp else ""
            replacement = match.group(repl_grp) if repl_grp else ""

            # Resolve skill hints
            if kind in ("forbid_skill", "require_skill", "add_step"):
                target = _SKILL_HINTS.get(target, target)
            elif kind == "add_output":
                target = _OUTPUT_HINTS.get(target, target)

            deltas.append(PlanDelta(
                kind=kind, target=target, replacement=replacement,
                reason=f"From: '{request}'",
            ))
            break  # one delta per request for now

    if not deltas:
        # Fallback: treat as goal amendment
        return RefinementRequest(
            raw_request=request,
            modified_goal=request,
        )

    return RefinementRequest(raw_request=request, deltas=deltas)


# ── Goal modification ────────────────────────────────────────────


def build_refined_goal(original_goal: str, refinement: RefinementRequest) -> str:
    """Build a modified goal string that incorporates the delta constraints."""
    if refinement.modified_goal:
        return f"{original_goal}. Additionally: {refinement.modified_goal}"

    parts = [original_goal]
    for delta in refinement.deltas:
        if delta.kind == "add_output":
            parts.append(f"Also output the {delta.target}")
        elif delta.kind == "forbid_skill":
            short = delta.target.split(".")[1] if "." in delta.target else delta.target
            parts.append(f"Do not {short}")
        elif delta.kind == "require_skill":
            short = delta.target.split(".")[1] if "." in delta.target else delta.target
            parts.append(f"Make sure to {short}")
        elif delta.kind == "add_step":
            short = delta.target.split(".")[1] if "." in delta.target else delta.target
            parts.append(f"Also {short} the result")
        elif delta.kind == "replace_presentation":
            parts.append(f"Format the output as a {delta.target}")

    return ". ".join(parts)


# ── Plan diff ────────────────────────────────────────────────────


class PlanDiff(BaseModel):
    """Structured difference between two plans."""

    added_steps: list[str] = Field(default_factory=list)
    removed_steps: list[str] = Field(default_factory=list)
    added_outputs: list[str] = Field(default_factory=list)
    removed_outputs: list[str] = Field(default_factory=list)
    changed_skills: list[str] = Field(default_factory=list)


def compute_diff(before: GlueGraph, after: GlueGraph) -> PlanDiff:
    """Compute structural diff between two plans."""
    before_steps = {n.id: n.config.get("skill_id", n.op) for n in before.graph.nodes}
    after_steps = {n.id: n.config.get("skill_id", n.op) for n in after.graph.nodes}

    before_skills = set(before_steps.values())
    after_skills = set(after_steps.values())

    before_outs = set(before.graph.outputs.keys())
    after_outs = set(after.graph.outputs.keys())

    return PlanDiff(
        added_steps=[f"{nid} ({after_steps[nid]})" for nid in after_steps if nid not in before_steps],
        removed_steps=[f"{nid} ({before_steps[nid]})" for nid in before_steps if nid not in after_steps],
        added_outputs=sorted(after_outs - before_outs),
        removed_outputs=sorted(before_outs - after_outs),
        changed_skills=sorted(after_skills - before_skills),
    )


def format_diff(diff: PlanDiff) -> str:
    """Format a PlanDiff for display."""
    lines: list[str] = []
    lines.append("  Plan Diff")
    lines.append("  " + "-" * 40)

    if diff.added_steps:
        lines.append("  Added steps:")
        for s in diff.added_steps:
            lines.append(f"    + {s}")
    if diff.removed_steps:
        lines.append("  Removed steps:")
        for s in diff.removed_steps:
            lines.append(f"    - {s}")
    if diff.added_outputs:
        lines.append(f"  Added outputs: {', '.join(diff.added_outputs)}")
    if diff.removed_outputs:
        lines.append(f"  Removed outputs: {', '.join(diff.removed_outputs)}")
    if diff.changed_skills:
        lines.append(f"  New skills: {', '.join(diff.changed_skills)}")

    if not any([diff.added_steps, diff.removed_steps, diff.added_outputs,
                diff.removed_outputs, diff.changed_skills]):
        lines.append("  (no structural changes)")

    return "\n".join(lines)
