"""Tests for the autogen smoke battery manifest and runner."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BATTERY = ROOT / "specs" / "autogen_prompt_battery.json"


def test_battery_manifest_exists() -> None:
    assert BATTERY.exists()


def test_battery_manifest_has_mixed_cases() -> None:
    cases = json.loads(BATTERY.read_text(encoding="utf-8"))
    expected = {case["expected"] for case in cases}
    assert "pass" in expected
    assert "out_of_scope" in expected
    assert "no_match" in expected


def test_positive_cases_define_template_key() -> None:
    cases = json.loads(BATTERY.read_text(encoding="utf-8"))
    positives = [case for case in cases if case["expected"] == "pass"]
    assert positives
    assert all(case.get("template_key") for case in positives)


def test_battery_manifest_has_adversarial_coverage() -> None:
    cases = json.loads(BATTERY.read_text(encoding="utf-8"))
    goals = {case["goal"] for case in cases}
    assert "convert this text to all caps" in goals
    assert "find the middle value of numbers" in goals
    assert "check whether this json key exists" in goals
