"""Op dispatch — maps op names to implementation functions."""
from __future__ import annotations

from typing import Any

from graphsmith.exceptions import OpError
from graphsmith.ops.array_ops import array_filter, array_map
from graphsmith.ops.assertion import assert_check
from graphsmith.ops.branch import branch_if
from graphsmith.ops.fallback import fallback_try
from graphsmith.ops.json_ops import json_parse
from graphsmith.ops.llm import llm_extract, llm_generate
from graphsmith.ops.llm_provider import LLMProvider, StubLLMProvider
from graphsmith.ops.parallel_map import parallel_map
from graphsmith.ops.select import select_fields
from graphsmith.ops.template import template_render
from graphsmith.ops.text_ops import (
    text_normalize,
    text_word_count,
    text_reverse,
    text_sort_lines,
    text_remove_duplicates,
    text_title_case,
)

# Ops that need no external provider
_PURE_OPS: dict[str, Any] = {
    "template.render": template_render,
    "json.parse": json_parse,
    "select.fields": select_fields,
    "assert.check": assert_check,
    "branch.if": branch_if,
    "fallback.try": fallback_try,
    "array.map": array_map,
    "array.filter": array_filter,
    "text.normalize": text_normalize,
    "text.word_count": text_word_count,
    "text.reverse": text_reverse,
    "text.sort_lines": text_sort_lines,
    "text.remove_duplicates": text_remove_duplicates,
    "text.title_case": text_title_case,
}


def execute_op(
    op: str,
    config: dict[str, Any],
    inputs: dict[str, Any],
    *,
    llm_provider: LLMProvider | None = None,
    registry: Any | None = None,
    depth: int = 0,
    call_stack: list[tuple[str, str]] | None = None,
) -> dict[str, Any] | tuple[dict[str, Any], Any]:
    """Dispatch to the correct op implementation.

    Returns a dict of output port -> value.
    For skill.invoke, returns (outputs, child_trace).
    """
    if op in _PURE_OPS:
        return _PURE_OPS[op](config, inputs)

    if op == "parallel.map":
        return parallel_map(config, inputs)

    if op == "llm.generate":
        provider = llm_provider or StubLLMProvider()
        return llm_generate(config, inputs, provider=provider)

    if op == "llm.extract":
        provider = llm_provider or StubLLMProvider()
        return llm_extract(config, inputs, provider=provider)

    if op == "skill.invoke":
        from graphsmith.ops.skill_invoke import skill_invoke
        return skill_invoke(
            config,
            inputs,
            registry=registry,
            llm_provider=llm_provider,
            depth=depth,
            call_stack=call_stack or [],
        )

    raise OpError(f"Unknown op '{op}'")
