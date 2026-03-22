"""Pure text ops: normalize, word_count, reverse, sort_lines, remove_duplicates, title_case, split, filter_lines, regex_extract."""
from __future__ import annotations

import re
from typing import Any

from graphsmith.exceptions import OpError


def text_normalize(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Normalize text: strip whitespace, collapse spaces, lowercase.

    Inputs:
        text (str): The text to normalize.

    Returns:
        {"normalized": <str>}
    """
    text = inputs.get("text")
    if text is None:
        raise OpError("text.normalize requires input 'text'")
    if not isinstance(text, str):
        raise OpError(f"text.normalize: 'text' must be a string, got {type(text).__name__}")

    normalized = re.sub(r"\s+", " ", text.strip()).lower()
    return {"normalized": normalized}


def text_word_count(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Count words in text.

    Inputs: text (str)
    Returns: {"count": <int as string>}
    """
    text = inputs.get("text")
    if text is None:
        raise OpError("text.word_count requires input 'text'")
    if not isinstance(text, str):
        raise OpError(f"text.word_count: 'text' must be a string, got {type(text).__name__}")
    count = len(text.split()) if text.strip() else 0
    return {"count": str(count)}


def text_reverse(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Reverse a string.

    Inputs: text (str)
    Returns: {"reversed": <str>}
    """
    text = inputs.get("text")
    if text is None:
        raise OpError("text.reverse requires input 'text'")
    return {"reversed": str(text)[::-1]}


def text_sort_lines(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Sort lines alphabetically.

    Inputs: text (str)
    Returns: {"sorted": <str>}
    """
    text = inputs.get("text")
    if text is None:
        raise OpError("text.sort_lines requires input 'text'")
    lines = str(text).split("\n")
    return {"sorted": "\n".join(sorted(lines))}


def text_remove_duplicates(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Remove duplicate lines, preserving order.

    Inputs: text (str)
    Returns: {"deduplicated": <str>}
    """
    text = inputs.get("text")
    if text is None:
        raise OpError("text.remove_duplicates requires input 'text'")
    seen: set[str] = set()
    out: list[str] = []
    for line in str(text).split("\n"):
        if line not in seen:
            seen.add(line)
            out.append(line)
    return {"deduplicated": "\n".join(out)}


def text_title_case(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Capitalize each word.

    Inputs: text (str)
    Returns: {"titled": <str>}
    """
    text = inputs.get("text")
    if text is None:
        raise OpError("text.title_case requires input 'text'")
    return {"titled": str(text).title()}


def text_split(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Split text by a delimiter.

    Inputs: text (str)
    Config: delimiter (str, default: newline)
    Returns: {"parts": <str> (newline-separated parts)}
    """
    text = inputs.get("text")
    if text is None:
        raise OpError("text.split requires input 'text'")
    delimiter = config.get("delimiter", "\n")
    parts = str(text).split(delimiter)
    return {"parts": "\n".join(p.strip() for p in parts if p.strip())}


def text_filter_lines(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Filter lines containing a substring.

    Inputs: text (str)
    Config: contains (str) — substring to match
    Returns: {"filtered": <str> (matching lines)}
    """
    text = inputs.get("text")
    if text is None:
        raise OpError("text.filter_lines requires input 'text'")
    pattern = config.get("contains", "")
    lines = str(text).split("\n")
    matched = [line for line in lines if pattern in line]
    return {"filtered": "\n".join(matched)}


def text_regex_extract(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Extract matches of a regex pattern from text.

    Inputs: text (str)
    Config: pattern (str) — regex pattern
    Returns: {"matches": <str> (newline-separated matches)}
    """
    text = inputs.get("text")
    if text is None:
        raise OpError("text.regex_extract requires input 'text'")
    pattern = config.get("pattern", "")
    if not pattern:
        raise OpError("text.regex_extract requires config 'pattern'")
    try:
        found = re.findall(pattern, str(text))
    except re.error as exc:
        raise OpError(f"text.regex_extract: invalid regex: {exc}") from exc
    return {"matches": "\n".join(str(m) for m in found)}
