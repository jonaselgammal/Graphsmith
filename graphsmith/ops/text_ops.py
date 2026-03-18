"""Pure text ops: normalize, word_count, reverse, sort_lines, remove_duplicates, title_case."""
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
