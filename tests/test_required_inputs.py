"""Regression tests for required-input satisfiability (Sprint 10G).

Covers the real-world failure where the LLM wired max_sentences as a
graph input but the user didn't provide it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphsmith.exceptions import ExecutionError
from graphsmith.models.common import IOField
from graphsmith.models.graph import GraphBody, GraphEdge, GraphNode
from graphsmith.ops.llm_provider import EchoLLMProvider
from graphsmith.planner.composer import glue_to_skill_package
from graphsmith.planner.models import GlueGraph, PlanRequest
from graphsmith.planner.prompt import build_planning_context
from graphsmith.registry import LocalRegistry
from graphsmith.registry.index import IndexEntry
from graphsmith.runtime import run_skill_package
from graphsmith.planner import run_glue_graph
from graphsmith.validator import validate_skill_package

from conftest import EXAMPLE_DIR, minimal_examples, minimal_graph, minimal_skill, write_package


# ── executor pre-check ───────────────────────────────────────────────


class TestExecutorRequiredInputCheck:
    def test_missing_required_input_fails_early(self, tmp_path: Path) -> None:
        """Graph declares text as required but user provides nothing."""
        write_package(
            tmp_path / "pkg",
            skill=minimal_skill(),
            graph=minimal_graph(),
            examples=minimal_examples(),
        )
        from graphsmith.parser import load_skill_package
        pkg = load_skill_package(tmp_path / "pkg")
        validate_skill_package(pkg)

        with pytest.raises(ExecutionError) as exc_info:
            run_skill_package(pkg, {})  # empty inputs
        msg = str(exc_info.value)
        assert "text" in msg
        assert "not provided" in msg.lower()

    def test_optional_input_can_be_omitted(self, tmp_path: Path) -> None:
        """Optional inputs in the skill contract don't trigger the pre-check."""
        from graphsmith.parser import load_skill_package
        pkg = load_skill_package(EXAMPLE_DIR / "text.normalize.v1")
        validate_skill_package(pkg)
        # text.normalize.v1 has only required 'text' — should pass
        result = run_skill_package(pkg, {"text": "hello"})
        assert result.trace.status == "ok"


# ── glue graph with unnecessary inputs ───────────────────────────────


class TestGlueGraphUnnecessaryInputs:
    def test_plan_with_extra_input_fails_at_runtime(self, tmp_path: Path) -> None:
        """A glue graph that declares max_sentences but user doesn't provide it."""
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")

        glue = GlueGraph(
            goal="summarize",
            inputs=[
                IOField(name="text", type="string"),
                IOField(name="max_sentences", type="integer"),  # required by default
            ],
            outputs=[IOField(name="summary", type="string")],
            effects=["llm_inference"],
            graph=GraphBody(
                version=1,
                nodes=[GraphNode(
                    id="call", op="skill.invoke",
                    config={"skill_id": "text.summarize.v1", "version": "1.0.0"},
                )],
                edges=[
                    GraphEdge(from_="input.text", to="call.text"),
                    GraphEdge(from_="input.max_sentences", to="call.max_sentences"),
                ],
                outputs={"summary": "call.summary"},
            ),
        )

        with pytest.raises(ExecutionError, match="max_sentences"):
            run_glue_graph(
                glue,
                {"text": "hello"},  # missing max_sentences
                llm_provider=EchoLLMProvider(prefix=""),
                registry=reg,
            )

    def test_plan_with_only_required_inputs_succeeds(self, tmp_path: Path) -> None:
        """A glue graph that only wires required inputs succeeds."""
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "text.normalize.v1")
        reg.publish(EXAMPLE_DIR / "text.extract_keywords.v1")

        glue = GlueGraph(
            goal="normalize and extract",
            inputs=[IOField(name="text", type="string")],
            outputs=[IOField(name="keywords", type="string")],
            effects=["llm_inference"],
            graph=GraphBody(
                version=1,
                nodes=[
                    GraphNode(id="norm", op="skill.invoke",
                              config={"skill_id": "text.normalize.v1", "version": "1.0.0"}),
                    GraphNode(id="kw", op="skill.invoke",
                              config={"skill_id": "text.extract_keywords.v1", "version": "1.0.0"}),
                ],
                edges=[
                    GraphEdge(from_="input.text", to="norm.text"),
                    GraphEdge(from_="norm.normalized", to="kw.text"),
                ],
                outputs={"keywords": "kw.keywords"},
            ),
        )

        result = run_glue_graph(
            glue,
            {"text": "hello"},
            llm_provider=EchoLLMProvider(prefix=""),
            registry=reg,
        )
        assert result.trace.status == "ok"


# ── candidate rendering ──────────────────────────────────────────────


class TestCandidateRendering:
    def test_prompt_shows_required_optional(self, tmp_path: Path) -> None:
        """Candidate inputs should be annotated with (required)/(optional)."""
        reg = LocalRegistry(root=tmp_path / "reg")
        reg.publish(EXAMPLE_DIR / "text.summarize.v1")

        from graphsmith.planner.candidates import retrieve_candidates
        candidates = retrieve_candidates("summarize", reg)
        request = PlanRequest(goal="summarize", candidates=candidates)
        ctx = build_planning_context(request)

        assert "text (required)" in ctx
        assert "max_sentences (optional)" in ctx

    def test_index_stores_required_optional(self, tmp_path: Path) -> None:
        reg = LocalRegistry(root=tmp_path / "reg")
        entry, _ = reg.publish(EXAMPLE_DIR / "text.summarize.v1")
        assert "text" in entry.required_input_names
        assert "max_sentences" in entry.optional_input_names


# ── prompt content ───────────────────────────────────────────────────


class TestPromptInputGuidance:
    def test_prompt_says_only_needed_inputs(self) -> None:
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        lower = ctx.lower()
        assert "only" in lower and "optional" in lower

    def test_prompt_example1_has_single_input(self) -> None:
        """Example 1 should not include max_sentences."""
        ctx = build_planning_context(PlanRequest(goal="test", candidates=[]))
        # Example 1 should have only text as input
        assert "max_sentences" not in ctx
