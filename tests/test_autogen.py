"""Tests for automatic skill generation (phase 2)."""
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
    run_generation_suite,
    validate_and_test,
)


# ── Spec extraction ───────────────────────────────────────────────


class TestExtractSpec:
    @pytest.mark.parametrize("goal,expected_key", [
        ("uppercase text", "uppercase"),
        ("convert to lowercase", "lowercase"),
        ("trim whitespace", "trim"),
        ("count characters", "char_count"),
        ("count the characters", "char_count"),
        ("count lines in text", "line_count"),
        ("join lines together", "join"),
        ("check if text starts with prefix", "starts_with"),
        ("check ends with suffix", "ends_with"),
        ("check if text contains word", "contains"),
        ("replace substring", "replace"),
        ("strip prefix from text", "strip_prefix"),
        ("remove suffix", "strip_suffix"),
        ("subtract two numbers", "subtract"),
        ("divide numbers", "divide"),
        ("find minimum of numbers", "min"),
        ("find the maximum", "max"),
        ("compute the median", "median"),
        ("get key from json", "get_key"),
        ("check if json has key", "has_key"),
        ("list json keys", "keys"),
        ("pretty print json", "pretty"),
        ("pretty print this json", "pretty"),
    ])
    def test_template_matching(self, goal: str, expected_key: str) -> None:
        spec = extract_spec(goal)
        assert spec.template_key == expected_key

    def test_spec_has_family(self) -> None:
        spec = extract_spec("uppercase text")
        assert spec.family == "text_unary"

    def test_unrecognized_raises(self) -> None:
        with pytest.raises(AutogenError, match="Could not match"):
            extract_spec("frobnicate the gizmo")

    @pytest.mark.parametrize("goal", [
        "fetch data from http API",
        "read file from disk",
        "delete file from system",
        "execute shell command",
        "create an autonomous agent loop",
    ])
    def test_out_of_scope(self, goal: str) -> None:
        with pytest.raises(AutogenError, match="Out of scope"):
            extract_spec(goal)


# ── Code generation ───────────────────────────────────────────────


class TestGenerateCode:
    def test_uppercase_code(self) -> None:
        code = generate_op_code(extract_spec("uppercase text"))
        assert "def text_uppercase" in code
        assert ".upper()" in code

    def test_math_code(self) -> None:
        code = generate_op_code(extract_spec("subtract"))
        assert "def math_subtract" in code

    def test_json_code(self) -> None:
        code = generate_op_code(extract_spec("json has key"))
        assert "def json_has_key" in code

    def test_contains_uses_input_not_config(self) -> None:
        code = generate_op_code(extract_spec("contains substring"))
        assert 'inputs.get("substring"' in code
        assert 'config.get("substring"' not in code


# ── File generation ───────────────────────────────────────────────


class TestGenerateFiles:
    def test_creates_all_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(extract_spec("uppercase text"), tmpdir)
            assert (path / "skill.yaml").is_file()
            assert (path / "graph.yaml").is_file()
            assert (path / "examples.yaml").is_file()

    def test_skill_yaml_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(extract_spec("trim text"), tmpdir)
            content = (path / "skill.yaml").read_text()
            assert "text.trim.v1" in content
            assert "pure" in content

    def test_graph_yaml_op(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(extract_spec("minimum"), tmpdir)
            content = (path / "graph.yaml").read_text()
            assert "op: math.min" in content

    def test_contains_skill_has_substring_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(extract_spec("contains substring"), tmpdir)
            content = (path / "skill.yaml").read_text()
            assert "name: substring" in content


# ── Validation + testing (all templates) ──────────────────────────


class TestValidateAllTemplates:
    """Every template should generate, validate, and pass examples."""

    @pytest.mark.parametrize("goal", [
        "uppercase text", "lowercase text", "trim text",
        "char count", "line count", "join lines",
        "starts with", "ends with", "contains substring",
        "replace text", "strip prefix", "strip suffix",
        "subtract numbers", "divide numbers",
        "minimum of numbers", "maximum of numbers", "median of numbers",
        "get key from json", "json has key", "json keys", "pretty print json",
    ])
    def test_template_end_to_end(self, goal: str) -> None:
        spec = extract_spec(goal)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            result = validate_and_test(spec, path)
            assert result["validation"] == "PASS", f"Validation failed: {result['errors']}"
            assert result["examples_passed"] == result["examples_total"], \
                f"Examples failed: {result['errors']}"


# ── Bulk harness ──────────────────────────────────────────────────


class TestBulkHarness:
    def test_run_generation_suite(self) -> None:
        summary = run_generation_suite()
        assert summary["total"] > 0
        assert summary["passed"] == summary["total"], \
            f"{summary['total'] - summary['passed']} templates failed"
        assert summary["validation_failures"] == 0
        assert summary["example_failures"] == 0


# ── Dry-run / format ─────────────────────────────────────────────


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
                  "errors": ["something broke"], "failure_stage": "validation"}
        text = format_result(result, Path("/tmp/test"))
        assert "FAIL" in text
        assert "Failure stage: validation" in text


class TestValidationStages:
    def test_registration_failure_stage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from graphsmith.skills import autogen as mod

        def fail_register(spec: SkillSpec) -> None:
            raise RuntimeError("boom")

        monkeypatch.setattr(mod, "register_generated_op", fail_register)
        spec = extract_spec("uppercase text")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            result = validate_and_test(spec, path)
        assert result["failure_stage"] == "registration"
        assert not result["passed"]

    def test_validation_failure_stage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import graphsmith.validator as validator_mod

        def fail_validate(pkg) -> None:
            raise RuntimeError("bad package")

        monkeypatch.setattr(validator_mod, "validate_skill_package", fail_validate)
        spec = extract_spec("uppercase text")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            result = validate_and_test(spec, path)
        assert result["failure_stage"] == "validation"
        assert not result["passed"]

    def test_examples_failure_stage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import graphsmith.ops.registry as registry_mod

        def wrong_output(op_name, config, inputs, **kwargs):
            return {"uppercased": "WRONG"}

        monkeypatch.setattr(registry_mod, "execute_op", wrong_output)
        spec = extract_spec("uppercase text")
        with tempfile.TemporaryDirectory() as tmpdir:
            path = generate_skill_files(spec, tmpdir)
            result = validate_and_test(spec, path)
        assert result["failure_stage"] == "examples"
        assert not result["passed"]


# ── No regression ────────────────────────────────────────────────


class TestNoRegression:
    def test_existing_create_skill(self) -> None:
        from graphsmith.skills.template import create_skill_template
        with tempfile.TemporaryDirectory() as tmpdir:
            path = create_skill_template("test.foo.v1", tmpdir)
            assert (path / "skill.yaml").is_file()
