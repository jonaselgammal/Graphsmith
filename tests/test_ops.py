"""Tests for individual primitive ops."""
from __future__ import annotations

import pytest

from graphsmith.exceptions import OpError
from graphsmith.ops.assertion import assert_check
from graphsmith.ops.branch import branch_if
from graphsmith.ops.fallback import fallback_try
from graphsmith.ops.json_ops import json_parse
from graphsmith.ops.llm import llm_extract, llm_generate
from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.ops.select import select_fields
from graphsmith.ops.template import template_render
from graphsmith.ops.text_ops import text_equals


# ── template.render ──────────────────────────────────────────────────


class TestTemplateRender:
    def test_basic(self) -> None:
        result = template_render(
            {"template": "Hello, {{name}}!"},
            {"name": "World"},
        )
        assert result == {"rendered": "Hello, World!"}

    def test_multiple_vars(self) -> None:
        result = template_render(
            {"template": "{{a}} + {{b}} = {{c}}"},
            {"a": "1", "b": "2", "c": "3"},
        )
        assert result == {"rendered": "1 + 2 = 3"}

    def test_integer_input(self) -> None:
        result = template_render(
            {"template": "Count: {{n}}"},
            {"n": 42},
        )
        assert result == {"rendered": "Count: 42"}

    def test_missing_template(self) -> None:
        with pytest.raises(OpError, match="config.template"):
            template_render({}, {"x": 1})

    def test_missing_variable_renders_empty(self) -> None:
        result = template_render({"template": "{{missing}}"}, {"x": 1})
        assert result == {"rendered": ""}


# ── json.parse ───────────────────────────────────────────────────────


class TestJsonParse:
    def test_object(self) -> None:
        result = json_parse({}, {"text": '{"a": 1}'})
        assert result == {"parsed": {"a": 1}}

    def test_array(self) -> None:
        result = json_parse({}, {"text": "[1, 2, 3]"})
        assert result == {"parsed": [1, 2, 3]}

    def test_missing_input(self) -> None:
        with pytest.raises(OpError, match="requires input 'text'"):
            json_parse({}, {})

    def test_invalid_json(self) -> None:
        with pytest.raises(OpError, match="invalid JSON"):
            json_parse({}, {"text": "not json"})

    def test_non_string(self) -> None:
        with pytest.raises(OpError, match="must be a string"):
            json_parse({}, {"text": 123})


# ── select.fields ────────────────────────────────────────────────────


class TestSelectFields:
    def test_basic(self) -> None:
        result = select_fields(
            {"fields": ["a", "c"]},
            {"data": {"a": 1, "b": 2, "c": 3}},
        )
        assert result == {"selected": {"a": 1, "c": 3}}

    def test_missing_field_ignored(self) -> None:
        result = select_fields(
            {"fields": ["a", "missing"]},
            {"data": {"a": 1}},
        )
        assert result == {"selected": {"a": 1}}

    def test_no_fields_config(self) -> None:
        with pytest.raises(OpError, match="config.fields"):
            select_fields({}, {"data": {"a": 1}})

    def test_non_dict_data(self) -> None:
        with pytest.raises(OpError, match="must be a dict"):
            select_fields({"fields": ["a"]}, {"data": "string"})


# ── assert.check ─────────────────────────────────────────────────────


class TestAssertCheck:
    def test_pass(self) -> None:
        result = assert_check({}, {"condition": True, "value": 42})
        assert result == {"value": 42}

    def test_pass_no_value(self) -> None:
        result = assert_check({}, {"condition": True})
        assert result == {"value": True}

    def test_fail(self) -> None:
        with pytest.raises(OpError, match="Assertion failed"):
            assert_check({}, {"condition": False})

    def test_fail_custom_message(self) -> None:
        with pytest.raises(OpError, match="must be positive"):
            assert_check(
                {"message": "must be positive"},
                {"condition": False},
            )

    def test_missing_condition(self) -> None:
        with pytest.raises(OpError, match="requires input 'condition'"):
            assert_check({}, {})


# ── branch.if ────────────────────────────────────────────────────────


class TestBranchIf:
    def test_true(self) -> None:
        result = branch_if(
            {},
            {"condition": True, "then_value": "yes", "else_value": "no"},
        )
        assert result == {"result": "yes"}

    def test_false(self) -> None:
        result = branch_if(
            {},
            {"condition": False, "then_value": "yes", "else_value": "no"},
        )
        assert result == {"result": "no"}

    def test_missing_condition(self) -> None:
        with pytest.raises(OpError, match="requires input 'condition'"):
            branch_if({}, {"then_value": "y"})


# ── fallback.try ─────────────────────────────────────────────────────


class TestFallbackTry:
    def test_primary_present(self) -> None:
        result = fallback_try({}, {"primary": "A", "fallback": "B"})
        assert result == {"result": "A"}

    def test_primary_none(self) -> None:
        result = fallback_try({}, {"primary": None, "fallback": "B"})
        assert result == {"result": "B"}

    def test_primary_missing(self) -> None:
        result = fallback_try({}, {"fallback": "B"})
        assert result == {"result": "B"}


class TestTextEquals:
    def test_equal(self) -> None:
        assert text_equals({}, {"text": "positive", "other": "positive"}) == {"result": True}

    def test_not_equal(self) -> None:
        assert text_equals({}, {"text": "negative", "other": "positive"}) == {"result": False}


# ── llm.generate ─────────────────────────────────────────────────────


class TestLLMGenerate:
    def test_echo(self) -> None:
        provider = EchoLLMProvider(prefix="echo:")
        result = llm_generate({}, {"prompt": "hello"}, provider=provider)
        assert result == {"text": "echo:hello"}

    def test_missing_prompt(self) -> None:
        provider = EchoLLMProvider()
        with pytest.raises(OpError, match="requires input 'prompt'"):
            llm_generate({}, {}, provider=provider)


# ── llm.extract ──────────────────────────────────────────────────────


class TestLLMExtract:
    def test_echo(self) -> None:
        provider = EchoLLMProvider(prefix="val:")
        result = llm_extract(
            {"schema": {"title": "string", "score": "number"}},
            {"prompt": "extract"},
            provider=provider,
        )
        assert result == {"extracted": {"title": "val:title", "score": "val:score"}}

    def test_missing_schema(self) -> None:
        provider = EchoLLMProvider()
        with pytest.raises(OpError, match="config.schema"):
            llm_extract({}, {"prompt": "x"}, provider=provider)
