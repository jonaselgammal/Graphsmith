"""Tests for parallel.map op."""
from __future__ import annotations

import pytest

from graphsmith.exceptions import OpError
from graphsmith.ops.parallel_map import parallel_map


class TestParallelMap:
    def test_template_render_per_item(self) -> None:
        result = parallel_map(
            {"op": "template.render", "op_config": {"template": "Hello, {{item}}!"}},
            {"items": ["alice", "bob", "charlie"]},
        )
        assert result == {
            "results": [
                {"rendered": "Hello, alice!"},
                {"rendered": "Hello, bob!"},
                {"rendered": "Hello, charlie!"},
            ]
        }

    def test_integer_items(self) -> None:
        result = parallel_map(
            {"op": "template.render", "op_config": {"template": "val={{item}}"}},
            {"items": [1, 2, 3]},
        )
        assert result == {
            "results": [
                {"rendered": "val=1"},
                {"rendered": "val=2"},
                {"rendered": "val=3"},
            ]
        }

    def test_empty_items(self) -> None:
        result = parallel_map(
            {"op": "template.render", "op_config": {"template": "{{item}}"}},
            {"items": []},
        )
        assert result == {"results": []}

    def test_deterministic_order(self) -> None:
        items = [f"item_{i}" for i in range(10)]
        r1 = parallel_map(
            {"op": "template.render", "op_config": {"template": "{{item}}"}},
            {"items": items},
        )
        r2 = parallel_map(
            {"op": "template.render", "op_config": {"template": "{{item}}"}},
            {"items": items},
        )
        assert r1 == r2

    def test_missing_items(self) -> None:
        with pytest.raises(OpError, match="requires input 'items'"):
            parallel_map({"op": "template.render"}, {})

    def test_items_not_list(self) -> None:
        with pytest.raises(OpError, match="must be a list"):
            parallel_map({"op": "template.render"}, {"items": "string"})

    def test_missing_op_config(self) -> None:
        with pytest.raises(OpError, match="requires config.op"):
            parallel_map({}, {"items": []})

    def test_skill_invoke_rejected(self) -> None:
        with pytest.raises(OpError, match="does not support skill.invoke"):
            parallel_map({"op": "skill.invoke"}, {"items": []})

    def test_nested_parallel_map_rejected(self) -> None:
        with pytest.raises(OpError, match="does not support nesting"):
            parallel_map({"op": "parallel.map"}, {"items": []})

    def test_unknown_inner_op_rejected(self) -> None:
        with pytest.raises(OpError, match="not a supported pure op"):
            parallel_map({"op": "magic.spell"}, {"items": []})

    def test_inner_op_error_propagates(self) -> None:
        """Inner op errors should propagate with item context."""
        # json.parse with non-string item will fail
        with pytest.raises(OpError, match="failed on item 0"):
            parallel_map(
                {"op": "json.parse"},
                {"items": [123]},  # json.parse expects string input 'text', gets 'item'
            )
