"""Tests for new skill ops and skill template generator."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from graphsmith.ops.math_ops import math_add, math_mean, math_multiply
from graphsmith.ops.text_ops import text_filter_lines, text_regex_extract, text_split
from graphsmith.skills.template import create_skill_template


# ── Text ops ───────────────────────────────────────────────────────


class TestTextSplit:
    def test_split_newlines(self) -> None:
        result = text_split({}, {"text": "a\nb\nc"})
        assert result["parts"] == "a\nb\nc"

    def test_split_custom_delimiter(self) -> None:
        result = text_split({"delimiter": ","}, {"text": "a,b,c"})
        assert result["parts"] == "a\nb\nc"

    def test_split_strips_empty(self) -> None:
        result = text_split({}, {"text": "a\n\nb"})
        assert result["parts"] == "a\nb"


class TestTextFilterLines:
    def test_filter_contains(self) -> None:
        result = text_filter_lines({"contains": "ERROR"}, {"text": "INFO ok\nERROR bad\nINFO done"})
        assert result["filtered"] == "ERROR bad"

    def test_filter_empty_pattern(self) -> None:
        result = text_filter_lines({"contains": ""}, {"text": "a\nb"})
        assert result["filtered"] == "a\nb"


class TestTextRegexExtract:
    def test_extract_numbers(self) -> None:
        result = text_regex_extract({"pattern": r"\d+"}, {"text": "abc 123 def 456"})
        assert result["matches"] == "123\n456"

    def test_invalid_regex(self) -> None:
        from graphsmith.exceptions import OpError
        with pytest.raises(OpError, match="invalid regex"):
            text_regex_extract({"pattern": "["}, {"text": "test"})

    def test_no_matches(self) -> None:
        result = text_regex_extract({"pattern": r"\d+"}, {"text": "no numbers here"})
        assert result["matches"] == ""


# ── Math ops ───────────────────────────────────────────────────────


class TestMathAdd:
    def test_add_integers(self) -> None:
        result = math_add({}, {"a": "3", "b": "4"})
        assert result["result"] == "7"

    def test_add_floats(self) -> None:
        result = math_add({}, {"a": "1.5", "b": "2.5"})
        assert result["result"] == "4"

    def test_add_negative(self) -> None:
        result = math_add({}, {"a": "-1", "b": "5"})
        assert result["result"] == "4"


class TestMathMultiply:
    def test_multiply(self) -> None:
        result = math_multiply({}, {"a": "3", "b": "5"})
        assert result["result"] == "15"

    def test_multiply_float(self) -> None:
        result = math_multiply({}, {"a": "2.5", "b": "4"})
        assert result["result"] == "10"


class TestMathMean:
    def test_mean(self) -> None:
        result = math_mean({}, {"values": "10\n20\n30"})
        assert result["result"] == "20"

    def test_mean_single(self) -> None:
        result = math_mean({}, {"values": "42"})
        assert result["result"] == "42"

    def test_mean_empty(self) -> None:
        from graphsmith.exceptions import OpError
        with pytest.raises(OpError, match="non-empty"):
            math_mean({}, {"values": ""})


# ── Skill template generator ──────────────────────────────────────


class TestSkillTemplate:
    def test_creates_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = create_skill_template("text.uppercase.v1", tmpdir)
            assert (path / "skill.yaml").is_file()
            assert (path / "graph.yaml").is_file()
            assert (path / "examples.yaml").is_file()

    def test_skill_yaml_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = create_skill_template("text.uppercase.v1", tmpdir)
            content = (path / "skill.yaml").read_text()
            assert "id: text.uppercase.v1" in content
            assert "Uppercase" in content
            assert "inputs:" in content
            assert "outputs:" in content

    def test_graph_yaml_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = create_skill_template("math.square.v1", tmpdir)
            content = (path / "graph.yaml").read_text()
            assert "op: math.square" in content

    def test_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            create_skill_template("test.skill.v1", tmpdir)
            create_skill_template("test.skill.v1", tmpdir)  # should not crash


# ── Skill packages validate ───────────────────────────────────────


class TestNewSkillPackagesValidate:
    @pytest.mark.parametrize("skill_name", [
        "text.split.v1",
        "math.add.v1",
        "math.multiply.v1",
        "math.mean.v1",
    ])
    def test_skill_validates(self, skill_name: str) -> None:
        from graphsmith.parser import load_skill_package
        from graphsmith.validator import validate_skill_package
        pkg = load_skill_package(f"examples/skills/{skill_name}")
        validate_skill_package(pkg)
