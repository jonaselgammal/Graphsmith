"""Tests for automatic skill generation prototype."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from graphsmith.skills.autogen import (
    AutogenError,
    SkillSpec,
    extract_spec,
    format_result,
    generate_op_code,
    generate_skill_files,
    register_generated_op,
    validate_and_test,
)


# ── Spec extraction ───────────────────────────────────────────────


class TestExtractSpec:
    def test_uppercase(self) -> None:
        spec = extract_spec("uppercase text")
        assert spec.template_key == "uppercase"
        assert spec.skill_id == "text.uppercase.v1"
        assert spec.category == "text"
        assert len(spec.examples) >= 2

    def test_lowercase(self) -> None:
        spec = extract_spec("convert to lowercase")
        assert spec.template_key == "lowercase"
        assert spec.skill_id == "text.lowercase.v1"

    def test_subtract(self) -> None:
        spec = extract_spec("subtract two numbers")
        assert spec.template_key == "subtract"
        assert spec.category == "math"

    def test_divide(self) -> None:
        spec = extract_spec("divide numbers")
        assert spec.template_key == "divide"

    def test_contains(self) -> None:
        spec = extract_spec("check if text contains a word")
        assert spec.template_key == "contains"

    def test_char_count(self) -> None:
        spec = extract_spec("count characters in text")
        assert spec.template_key == "char_count"

    def test_json_get_key(self) -> None:
        spec = extract_spec("get key from json")
        assert spec.template_key == "get_key"
        assert spec.category == "json"

    def test_strip_prefix(self) -> None:
        spec = extract_spec("remove prefix from text")
        assert spec.template_key == "strip_prefix"

    def test_unrecognized_raises(self) -> None:
        with pytest.raises(AutogenError, match="Could not match"):
            extract_spec("frobnicate the gizmo")

    def test_out_of_scope_network(self) -> None:
        with pytest.raises(AutogenError, match="Out of scope"):
            extract_spec("fetch data from http API")

    def test_out_of_scope_file(self) -> None:
        with pytest.raises(AutogenError, match="Out of scope"):
            extract_spec("read file from disk")

    def test_out_of_scope_delete_file(self) -> None:
        with pytest.raises(AutogenError, match="Out of scope"):
            extract_spec("delete file from disk")

    def test_out_of_scope_shell(self) -> None:
        with pytest.raises(AutogenError, match="Out of scope"):
            extract_spec("execute shell command")

    def test_out_of_scope_agent(self) -> None:
        with pytest.raises(AutogenError, match="Out of scope"):
            extract_spec("create an autonomous agent loop")


# ── Code generation ───────────────────────────────────────────────


class TestGenerateCode:
    def test_uppercase_code(self) -> None:
        spec = extract_spec("uppercase text")
        code = generate_op_code(spec)
        assert "def text_uppercase" in code
        assert ".upper()" in code

    def test_subtract_code(self) -> None:
        spec = extract_spec("subtract")
        code = generate_op_code(spec)
        assert "def math_subtract" in code


# ── File generation ───────────────────────────────────────────────


class TestGenerateFiles:
    def test_creates_all_files(self) -> None:
        spec = extract_spec("uppercase text")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            assert (path / "skill.yaml").is_file()
            assert (path / "graph.yaml").is_file()
            assert (path / "examples.yaml").is_file()

    def test_skill_yaml_content(self) -> None:
        spec = extract_spec("uppercase text")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            content = (path / "skill.yaml").read_text()
            assert "id: text.uppercase.v1" in content
            assert "uppercase" in content.lower()

    def test_graph_yaml_references_op(self) -> None:
        spec = extract_spec("uppercase text")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            content = (path / "graph.yaml").read_text()
            assert "op: text.uppercase" in content

    def test_examples_yaml_has_entries(self) -> None:
        spec = extract_spec("uppercase text")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            content = (path / "examples.yaml").read_text()
            assert "HELLO WORLD" in content


# ── Validation + testing ──────────────────────────────────────────


class TestValidateAndTest:
    def test_uppercase_passes(self) -> None:
        spec = extract_spec("uppercase text")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            result = validate_and_test(spec, path)
            assert result["validation"] == "PASS"
            assert result["examples_passed"] == result["examples_total"]
            assert result["examples_total"] >= 2

    def test_lowercase_passes(self) -> None:
        spec = extract_spec("lowercase text")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            result = validate_and_test(spec, path)
            assert result["validation"] == "PASS"
            assert result["examples_passed"] == result["examples_total"]

    def test_subtract_passes(self) -> None:
        spec = extract_spec("subtract numbers")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            result = validate_and_test(spec, path)
            assert result["validation"] == "PASS"
            assert result["examples_passed"] == result["examples_total"]

    def test_divide_passes(self) -> None:
        spec = extract_spec("divide numbers")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            result = validate_and_test(spec, path)
            assert result["validation"] == "PASS"
            assert result["examples_passed"] == result["examples_total"]

    def test_char_count_passes(self) -> None:
        spec = extract_spec("character count")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            result = validate_and_test(spec, path)
            assert result["validation"] == "PASS"
            assert result["examples_passed"] == result["examples_total"]

    def test_json_get_key_passes(self) -> None:
        spec = extract_spec("get key from json")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            result = validate_and_test(spec, path)
            assert result["validation"] == "PASS"
            assert result["examples_passed"] == result["examples_total"]


# ── Format result ─────────────────────────────────────────────────


class TestFormatResult:
    def test_format_pass(self) -> None:
        result = {"skill_id": "test", "validation": "PASS",
                  "examples_total": 3, "examples_passed": 3, "errors": []}
        text = format_result(result, Path("/tmp/test"))
        assert "PASS" in text
        assert "3/3" in text

    def test_format_fail(self) -> None:
        result = {"skill_id": "test", "validation": "FAIL",
                  "examples_total": 0, "examples_passed": 0,
                  "errors": ["something broke"]}
        text = format_result(result, Path("/tmp/test"))
        assert "FAIL" in text
        assert "something broke" in text


# ── Existing create-skill still works ─────────────────────────────


class TestNoRegression:
    def test_existing_create_skill(self) -> None:
        from graphsmith.skills.template import create_skill_template
        with tempfile.TemporaryDirectory() as tmpdir:
            path = create_skill_template("test.foo.v1", tmpdir)
            assert (path / "skill.yaml").is_file()
