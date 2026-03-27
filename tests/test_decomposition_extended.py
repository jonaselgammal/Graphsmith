"""Extended deterministic decomposition coverage for stress-frontier chains."""
from __future__ import annotations

from graphsmith.planner.decomposition import decompose_deterministic


def test_decompose_sort_dedupe_join_pipeline() -> None:
    d = decompose_deterministic(
        "Take these lines of pseudo-code, normalize them, sort them, remove duplicates, and join them into a readable block",
    )
    assert d.content_transforms == [
        "normalize",
        "sort_lines",
        "remove_duplicates",
        "join_lines",
    ]
    assert d.final_output_names == ["joined"]


def test_decompose_json_pretty_contains_chain_has_json_steps() -> None:
    d = decompose_deterministic(
        "Parse this JSON, extract the value field, pretty print it as JSON, and check whether the formatted result contains a phrase",
    )
    assert "extract_field" in d.content_transforms
    assert "pretty_print" in d.content_transforms
