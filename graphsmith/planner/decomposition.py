"""Semantic decomposition — explicit intent before IR generation.

The decomposition captures WHAT the plan should do at a semantic level,
separating content transforms from presentation and pinning output names.
This feeds the IR generator as a binding contract.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from graphsmith.planner.ir_parser import _extract_json_text  # reuse JSON extraction
from graphsmith.planner.models import PlanRequest


# ── Schema ─────────────────────────────────────────────────────────


class SemanticDecomposition(BaseModel):
    """Compact semantic intent for a planning goal."""

    content_transforms: list[str] = Field(default_factory=list)
    presentation: Literal["none", "list", "header", "template"] = "none"
    final_output_names: list[str] = Field(default_factory=list)
    reasoning: str = ""


# ── Prompt ─────────────────────────────────────────────────────────


_DECOMP_SYSTEM = (
    "You are a task decomposer. Analyze the user's goal and produce a JSON "
    "decomposition. Respond with JSON only."
)

_DECOMP_PROMPT = """\
# Task

Analyze this goal and decompose it into content transforms and presentation intent.

Goal: "{goal}"

Available skills:
{skills}

# Required JSON output

```json
{{
  "content_transforms": ["..."],
  "presentation": "none" | "list" | "header" | "template",
  "final_output_names": ["..."],
  "reasoning": "..."
}}
```

## Rules

"content_transforms": list the CONTENT processing steps needed, in order.
Use these exact labels:
- "normalize" — clean up, tidy, lowercase, trim
- "summarize" — summarize, condense, brief summary
- "extract_keywords" — extract keywords, find topics, pull out key topics
- "title_case" — capitalize each word, title case
- "classify_sentiment" — analyze sentiment
- "word_count" — count words, how many words
- "sort_lines" — sort lines, order items alphabetically
- "remove_duplicates" — remove duplicates, deduplicate
- "join_lines" — join lines into a readable block
- "extract_field" — parse JSON and extract a single field (the value field)
- "reshape_json" — parse/reshape JSON, select multiple fields (name and value)
- "pretty_print" — pretty print JSON or format JSON for readability

"presentation": how should the final result be presented?
- "none" — no formatting, return raw skill output
- "list" — format as a list (uses join_lines)
- "header" — add a header/prefix (uses template.render with constant in template)
- "template" — custom template rendering

If the goal does NOT mention format/list/bullet/header/present/readable/nicely,
use "none". Most goals use "none".

"final_output_names": the output port names the user gets back.
Use the SKILL output port names:
- normalize → "normalized"
- summarize → "summary"
- extract_keywords → "keywords"
- title_case → "titled"
- classify_sentiment → "sentiment"
- word_count → "count"
- sort_lines → "sorted"
- remove_duplicates → "deduplicated"
- join_lines → "joined"
- extract_field → "value"
- reshape_json → "selected"
- pretty_print → "formatted"
- list presentation → "joined"
- header/template presentation → "rendered"

If the goal requests MULTIPLE deliverables (uses "and"), include ALL their output names.
If only the final result is requested, include only the endpoint output.

## Examples

Goal: "Extract keywords from this text"
→ {{"content_transforms": ["extract_keywords"], "presentation": "none", "final_output_names": ["keywords"]}}

Goal: "Find the key topics in this text"
→ {{"content_transforms": ["extract_keywords"], "presentation": "none", "final_output_names": ["keywords"]}}

Goal: "Extract keywords and format them as a list"
→ {{"content_transforms": ["extract_keywords"], "presentation": "list", "final_output_names": ["joined"]}}

Goal: "Extract keywords and add a header saying Results"
→ {{"content_transforms": ["extract_keywords"], "presentation": "header", "final_output_names": ["rendered"]}}

Goal: "Tidy up this text and find the key topics"
→ {{"content_transforms": ["normalize", "extract_keywords"], "presentation": "none", "final_output_names": ["normalized", "keywords"]}}

Goal: "Clean up this text and capitalize each word"
→ {{"content_transforms": ["normalize", "title_case"], "presentation": "none", "final_output_names": ["titled"]}}

Goal: "Normalize this text and count the words"
→ {{"content_transforms": ["normalize", "word_count"], "presentation": "none", "final_output_names": ["normalized", "count"]}}

Goal: "Normalize these lines, sort them, remove duplicates, and join them into a readable block"
→ {{"content_transforms": ["normalize", "sort_lines", "remove_duplicates", "join_lines"], "presentation": "none", "final_output_names": ["joined"]}}

Goal: "Extract the name and value from this JSON"
→ {{"content_transforms": ["reshape_json"], "presentation": "none", "final_output_names": ["selected"]}}

Goal: "Parse this JSON and extract the value field"
→ {{"content_transforms": ["extract_field"], "presentation": "none", "final_output_names": ["value"]}}

Goal: "Parse this JSON and pretty print it"
→ {{"content_transforms": ["pretty_print"], "presentation": "none", "final_output_names": ["formatted"]}}

Goal: "Clean up the text, pull out key topics, and format them with a header"
→ {{"content_transforms": ["normalize", "extract_keywords"], "presentation": "header", "final_output_names": ["rendered"]}}
"""


def build_decomposition_prompt(request: PlanRequest) -> str:
    """Build the decomposition prompt for a given goal."""
    if request.candidates:
        skill_lines = []
        for c in request.candidates:
            outs = ", ".join(c.output_names) or "(none)"
            skill_lines.append(f"- {c.id}: outputs [{outs}]")
        skills = "\n".join(skill_lines)
    else:
        skills = "(none)"
    return _DECOMP_PROMPT.format(goal=request.goal, skills=skills)


def get_decomp_system_message() -> str:
    return _DECOMP_SYSTEM


# ── Parser ─────────────────────────────────────────────────────────


class DecompositionParseError(Exception):
    """Failed to parse decomposition output."""
    pass


def parse_decomposition(raw: str) -> SemanticDecomposition:
    """Parse LLM output into a SemanticDecomposition."""
    text = _extract_json_text(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DecompositionParseError(f"Invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise DecompositionParseError(f"Expected object, got {type(data).__name__}")

    presentation = data.get("presentation", "none")
    if presentation not in ("none", "list", "header", "template"):
        presentation = "none"

    # Normalize final_output_names: LLM sometimes returns a dict instead of list
    raw_outputs = data.get("final_output_names", [])
    if isinstance(raw_outputs, dict):
        final_output_names = list(raw_outputs.values())
    elif isinstance(raw_outputs, list):
        final_output_names = raw_outputs
    else:
        final_output_names = []

    return SemanticDecomposition(
        content_transforms=data.get("content_transforms", []),
        presentation=presentation,
        final_output_names=final_output_names,
        reasoning=data.get("reasoning", ""),
    )


# ── Deterministic fallback decomposition ───────────────────────────

# Maps goal keywords to transform labels
_KEYWORD_TRANSFORMS: list[tuple[set[str], str]] = [
    ({"clean", "tidy", "normalize", "cleanup", "lowercase", "trim"}, "normalize"),
    ({"summarize", "summary", "condense", "brief"}, "summarize"),
    ({"keyword", "keywords", "topic", "topics"}, "extract_keywords"),
    ({"capitalize", "title case", "capital letter", "title_case"}, "title_case"),
    ({"sentiment"}, "classify_sentiment"),
    ({"count", "word count", "how many words"}, "word_count"),
    ({"sort", "order alphabetically", "alphabetical"}, "sort_lines"),
    ({"remove duplicates", "deduplicate", "unique"}, "remove_duplicates"),
    ({"join", "readable block"}, "join_lines"),
    ({"pretty print", "formatted json", "readable json"}, "pretty_print"),
    ({"json", "reshape"}, "reshape_json"),
]

# Phrase-level patterns checked before keyword transforms (more specific).
# Longer/more-specific phrases first so they match before shorter ones.
_PHRASE_TRANSFORMS: list[tuple[str, str]] = [
    ("parse and reshape", "reshape_json"),
    ("reshape json", "reshape_json"),
    ("pretty print", "pretty_print"),
    ("pretty-print", "pretty_print"),
    ("name and value", "reshape_json"),
    ("extract the value", "extract_field"),
    ("extract the field", "extract_field"),
    ("extract field", "extract_field"),
    ("value field", "extract_field"),
    ("remove duplicates", "remove_duplicates"),
    ("join them into", "join_lines"),
    ("join into", "join_lines"),
]

_TRANSFORM_OUTPUT_PORT: dict[str, str] = {
    "normalize": "normalized",
    "summarize": "summary",
    "extract_keywords": "keywords",
    "title_case": "titled",
    "classify_sentiment": "sentiment",
    "word_count": "count",
    "sort_lines": "sorted",
    "remove_duplicates": "deduplicated",
    "join_lines": "joined",
    "reshape_json": "selected",
    "extract_field": "value",
    "pretty_print": "formatted",
}

_FORMATTING_KEYWORDS = {"format", "list", "bullet", "readable", "nicely"}
_HEADER_KEYWORDS = {"header", "prefix"}


def decompose_deterministic(goal: str) -> SemanticDecomposition:
    """Deterministic fallback decomposition from goal text.

    Used when LLM decomposition fails or for testing.
    """
    goal_lower = goal.lower()
    matched_positions: dict[str, int] = {}

    # Phase 1: check phrase-level patterns (more specific, checked first)
    # Longer phrases checked first; once a JSON transform matches, skip others
    json_phrase_matched = False
    for phrase, label in _PHRASE_TRANSFORMS:
        pos = goal_lower.find(phrase)
        if pos != -1:
            is_json_label = label in ("reshape_json", "extract_field")
            if is_json_label and json_phrase_matched:
                continue  # only one JSON transform from phrases
            prev = matched_positions.get(label)
            if prev is None or pos < prev:
                matched_positions[label] = pos
            if is_json_label:
                json_phrase_matched = True

    # Phase 2: check keyword-level patterns (skip if phrase already matched)
    for keywords, label in _KEYWORD_TRANSFORMS:
        # Skip generic JSON keyword match if a specific JSON phrase already matched
        if label == "reshape_json" and json_phrase_matched:
            continue
        positions = [goal_lower.find(kw) for kw in keywords if goal_lower.find(kw) != -1]
        if positions:
            pos = min(positions)
            prev = matched_positions.get(label)
            if prev is None or pos < prev:
                matched_positions[label] = pos

    transforms = [
        label for label, _ in sorted(matched_positions.items(), key=lambda item: (item[1], item[0]))
    ]

    # Presentation
    words = set(re.findall(r"[a-z]+", goal_lower))
    if words & _HEADER_KEYWORDS:
        presentation = "header"
    elif words & _FORMATTING_KEYWORDS:
        presentation = "list"
    else:
        presentation = "none"

    # Final output names
    output_names: list[str] = []
    if presentation == "list":
        output_names = ["joined"]
    elif presentation in ("header", "template"):
        output_names = ["rendered"]
    else:
        # Multi-output: expose all transform outputs if goal uses "and"
        if " and " in goal_lower or "," in goal_lower:
            output_names = [_TRANSFORM_OUTPUT_PORT[t] for t in transforms if t in _TRANSFORM_OUTPUT_PORT]
        elif transforms:
            last = transforms[-1]
            output_names = [_TRANSFORM_OUTPUT_PORT.get(last, last)]

    return SemanticDecomposition(
        content_transforms=transforms,
        presentation=presentation,
        final_output_names=output_names,
        reasoning="deterministic decomposition",
    )
