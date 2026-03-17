"""Tests for array.map and array.filter ops."""
from __future__ import annotations

import pytest

from graphsmith.exceptions import OpError
from graphsmith.ops.array_ops import array_filter, array_map


# ── array.map ────────────────────────────────────────────────────────


class TestArrayMap:
    def test_field_projection(self) -> None:
        result = array_map(
            {"field": "name"},
            {"items": [{"name": "alice"}, {"name": "bob"}]},
        )
        assert result == {"mapped": ["alice", "bob"]}

    def test_template_mode(self) -> None:
        result = array_map(
            {"template": "Hello, {{item}}!"},
            {"items": ["alice", "bob"]},
        )
        assert result == {"mapped": ["Hello, alice!", "Hello, bob!"]}

    def test_empty_array(self) -> None:
        result = array_map({"field": "x"}, {"items": []})
        assert result == {"mapped": []}

    def test_missing_items(self) -> None:
        with pytest.raises(OpError, match="requires input 'items'"):
            array_map({"field": "x"}, {})

    def test_items_not_list(self) -> None:
        with pytest.raises(OpError, match="must be a list"):
            array_map({"field": "x"}, {"items": "not a list"})

    def test_both_field_and_template(self) -> None:
        with pytest.raises(OpError, match="not both"):
            array_map({"field": "x", "template": "{{item}}"}, {"items": []})

    def test_neither_field_nor_template(self) -> None:
        with pytest.raises(OpError, match="must include"):
            array_map({}, {"items": []})

    def test_missing_field_in_item(self) -> None:
        with pytest.raises(OpError, match="no field"):
            array_map({"field": "x"}, {"items": [{"y": 1}]})

    def test_item_not_dict_in_field_mode(self) -> None:
        with pytest.raises(OpError, match="not a dict"):
            array_map({"field": "x"}, {"items": ["string"]})


# ── array.filter ─────────────────────────────────────────────────────


class TestArrayFilter:
    def test_truthy_filter(self) -> None:
        items = [{"active": True, "n": "a"}, {"active": False, "n": "b"}, {"active": 1, "n": "c"}]
        result = array_filter({"field": "active"}, {"items": items})
        assert result == {"filtered": [{"active": True, "n": "a"}, {"active": 1, "n": "c"}]}

    def test_equality_filter(self) -> None:
        items = [{"color": "red"}, {"color": "blue"}, {"color": "red"}]
        result = array_filter({"field": "color", "value": "red"}, {"items": items})
        assert result == {"filtered": [{"color": "red"}, {"color": "red"}]}

    def test_empty_array(self) -> None:
        result = array_filter({"field": "x"}, {"items": []})
        assert result == {"filtered": []}

    def test_no_matches(self) -> None:
        result = array_filter(
            {"field": "x", "value": "nope"},
            {"items": [{"x": "yes"}]},
        )
        assert result == {"filtered": []}

    def test_missing_items(self) -> None:
        with pytest.raises(OpError, match="requires input 'items'"):
            array_filter({"field": "x"}, {})

    def test_missing_field_config(self) -> None:
        with pytest.raises(OpError, match="config.field"):
            array_filter({}, {"items": []})

    def test_non_dict_items_skipped(self) -> None:
        items = [{"x": 1}, "string", {"x": 2}]
        result = array_filter({"field": "x"}, {"items": items})
        assert result == {"filtered": [{"x": 1}, {"x": 2}]}

    def test_missing_field_in_item_skipped(self) -> None:
        items = [{"x": 1}, {"y": 2}, {"x": 3}]
        result = array_filter({"field": "x"}, {"items": items})
        assert result == {"filtered": [{"x": 1}, {"x": 3}]}
