"""text.normalize op — deterministic text cleanup."""
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
