"""Tests for parallel.map op."""
from __future__ import annotations

from pathlib import Path

import pytest

from graphsmith.exceptions import OpError
from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.ops.parallel_map import parallel_map
from graphsmith.registry import LocalRegistry

from conftest import EXAMPLE_DIR


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

    def test_skill_invoke_per_item(self, tmp_path: Path) -> None:
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "text.normalize.v1")

        result = parallel_map(
            {
                "op": "skill.invoke",
                "item_input": "text",
                "op_config": {"skill_id": "text.normalize.v1", "version": "1.0.0"},
            },
            {"items": ["  Alice ", "Bob  "]},
            registry=reg,
        )
        assert result == {
            "results": [
                {"normalized": "alice"},
                {"normalized": "bob"},
            ]
        }

    def test_skill_invoke_can_aggregate_named_outputs(self, tmp_path: Path) -> None:
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "text.normalize.v1")

        result = parallel_map(
            {
                "op": "skill.invoke",
                "item_input": "text",
                "aggregate_outputs": True,
                "op_config": {"skill_id": "text.normalize.v1", "version": "1.0.0"},
            },
            {"items": ["  Alice ", "Bob  "]},
            registry=reg,
        )
        assert result == {
            "results": [
                {"normalized": "alice"},
                {"normalized": "bob"},
            ],
            "normalized": ["alice", "bob"],
        }

    def test_nested_parallel_map_rejected(self) -> None:
        with pytest.raises(OpError, match="does not support nesting"):
            parallel_map({"op": "parallel.map"}, {"items": []})

    def test_unknown_inner_op_rejected(self) -> None:
        with pytest.raises(OpError, match="is not supported"):
            parallel_map({"op": "magic.spell"}, {"items": []})

    def test_inner_op_error_propagates(self) -> None:
        """Inner op errors should propagate with item context."""
        # json.parse with non-string item will fail
        with pytest.raises(OpError, match="failed on item 0"):
            parallel_map(
                {"op": "json.parse"},
                {"items": [123]},  # json.parse expects string input 'text', gets 'item'
            )

    def test_item_input_alias_for_pure_op(self) -> None:
        result = parallel_map(
            {"op": "template.render", "item_input": "name", "op_config": {"template": "Hello, {{name}}!"}},
            {"items": ["alice", "bob"]},
        )
        assert result == {
            "results": [
                {"rendered": "Hello, alice!"},
                {"rendered": "Hello, bob!"},
            ]
        }

    def test_extra_inputs_passthrough(self) -> None:
        result = parallel_map(
            {"op": "template.render", "item_input": "value", "op_config": {"template": "{{prefix}}:{{value}}"}},
            {"items": ["a", "b"], "prefix": "item"},
        )
        assert result == {
            "results": [
                {"rendered": "item:a"},
                {"rendered": "item:b"},
            ]
        }

    def test_max_items_enforced(self) -> None:
        with pytest.raises(OpError, match="exceeds configured limit 1"):
            parallel_map(
                {"op": "template.render", "max_items": 1, "op_config": {"template": "{{item}}"}},
                {"items": ["a", "b"]},
            )

    def test_bad_max_items_rejected(self) -> None:
        with pytest.raises(OpError, match="config.max_items"):
            parallel_map(
                {"op": "template.render", "max_items": -1, "op_config": {"template": "{{item}}"}},
                {"items": ["a"]},
            )

    def test_skill_invoke_needs_registry(self) -> None:
        with pytest.raises(OpError, match="requires a registry"):
            parallel_map(
                {
                    "op": "skill.invoke",
                    "item_input": "text",
                    "op_config": {"skill_id": "text.normalize.v1", "version": "1.0.0"},
                },
                {"items": ["a"]},
            )

    def test_skill_invoke_with_llm_provider(self, tmp_path: Path) -> None:
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")

        result = parallel_map(
            {
                "op": "skill.invoke",
                "item_input": "text",
                "op_config": {"skill_id": "text.summarize.v1", "version": "1.0.0"},
            },
            {"items": ["cats"], "max_sentences": 1},
            registry=reg,
            llm_provider=EchoLLMProvider(prefix=""),
        )
        assert "cats" in result["results"][0]["summary"]
