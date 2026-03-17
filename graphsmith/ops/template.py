"""template.render op — Mustache-style variable substitution."""
from __future__ import annotations

import re
from typing import Any

from graphsmith.exceptions import OpError


def template_render(config: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Render a template string using ``{{var}}`` placeholders.

    Config:
        template (str): The template string with ``{{var}}`` placeholders.

    Inputs:
        Arbitrary key/value pairs used as template variables.

    Returns:
        {"rendered": <str>}
    """
    template = config.get("template")
    if not template or not isinstance(template, str):
        raise OpError("template.render requires config.template (string)")

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key not in inputs:
            # Variable not bound — render as empty string.
            # This supports optional inputs that were not provided.
            return ""
        return str(inputs[key])

    rendered = re.sub(r"\{\{(.+?)\}\}", _replace, template)
    return {"rendered": rendered}
