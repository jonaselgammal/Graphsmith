"""Interactive planning session — inspect candidates, compare, trace, debug."""
from __future__ import annotations

import json
from typing import Any

import typer

from graphsmith.planner.ir_backend import CandidateResult, IRPlannerBackend

_ARROW = " \u2192 "  # → character, extracted for Python 3.11 f-string compat
from graphsmith.planner.models import GlueGraph, PlanResult
from graphsmith.traces.models import RunTrace


# ── Formatting helpers ─────────────────────────────────────────────


def format_plan_summary(glue: GlueGraph) -> str:
    """Format a GlueGraph as a clean plan summary."""
    lines: list[str] = []
    lines.append("  Plan Summary")
    lines.append("  " + "-" * 40)

    # Flow chain
    chain = " \u2192 ".join(n.id for n in glue.graph.nodes)
    lines.append(f"  Flow: {chain}")

    lines.append("  Steps:")
    for i, node in enumerate(glue.graph.nodes, 1):
        skill = node.config.get("skill_id", node.op)
        lines.append(f"    {i}. {node.id} ({skill})")
    lines.append("  Outputs:")
    for name, addr in glue.graph.outputs.items():
        lines.append(f"    - {name} \u2190 {addr}")
    if glue.effects:
        lines.append(f"  Effects: {', '.join(glue.effects)}")
    return "\n".join(lines)


def format_candidates(candidates: list[CandidateResult]) -> str:
    if not candidates:
        return "  No candidates available."
    lines: list[str] = []
    compiled = [x for x in candidates if x.status == "compiled" and x.score]
    best_idx = max(compiled, key=lambda x: x.score.total if x.score else 0).index if compiled else -1

    for c in candidates:
        selected = " \u2714 SELECTED" if c.index == best_idx else ""
        lines.append(f"  Candidate {c.index + 1}:{selected}")
        if c.status != "compiled":
            lines.append(f"    status: {c.status}")
            if c.error:
                lines.append(f"    error: {c.error[:80]}")
        else:
            if c.ir:
                lines.append(f"    steps: {_ARROW.join(s.name for s in c.ir.steps)}")
                lines.append(f"    outputs: {', '.join(c.ir.final_outputs.keys())}")
            if c.score:
                lines.append(f"    score: {c.score.total:.0f}")
                if c.score.penalties:
                    lines.append(f"    penalties: {'; '.join(r for r, _ in c.score.penalties[:3])}")
                if c.score.rewards:
                    lines.append(f"    rewards: {'; '.join(r for r, _ in c.score.rewards[:3])}")
        lines.append("")
    return "\n".join(lines)


def format_compare(candidates: list[CandidateResult]) -> str:
    compiled = [c for c in candidates if c.status == "compiled" and c.score]
    if len(compiled) < 2:
        return "  Not enough candidates to compare."
    ranked = sorted(compiled, key=lambda c: c.score.total if c.score else 0, reverse=True)
    best, alt = ranked[0], ranked[1]
    lines: list[str] = []
    for label, c in [("Selected", best), ("Alternative", alt)]:
        lines.append(f"  {label} (Candidate {c.index + 1})")
        if c.ir:
            lines.append(f"    steps: {_ARROW.join(s.name for s in c.ir.steps)}")
            lines.append(f"    outputs: {', '.join(c.ir.final_outputs.keys())}")
        lines.append(f"    score: {c.score.total:.0f}" if c.score else "")
        lines.append("")
    if best.ir and alt.ir:
        best_s = {s.skill_id for s in best.ir.steps}
        alt_s = {s.skill_id for s in alt.ir.steps}
        lines.append("  Differences:")
        if best_s - alt_s:
            lines.append(f"    selected has: {', '.join(sorted(best_s - alt_s))}")
        if alt_s - best_s:
            lines.append(f"    alternative has: {', '.join(sorted(alt_s - best_s))}")
        if not (best_s - alt_s) and not (alt_s - best_s):
            lines.append("    same skills, different scores")
        if best.score and alt.score:
            lines.append(f"    score delta: +{best.score.total - alt.score.total:.0f}")
    return "\n".join(lines)


def format_trace(trace: RunTrace) -> str:
    """Format an execution trace for display."""
    lines: list[str] = []
    lines.append("  Execution Trace")
    lines.append("  " + "-" * 40)
    for i, nt in enumerate(trace.nodes, 1):
        status_icon = "\u2714" if nt.status == "ok" else "\u2716"
        skill = nt.op
        lines.append(f"  Step {i}: {nt.node_id} ({skill}) {status_icon}")
        if nt.inputs_summary:
            for k, v in nt.inputs_summary.items():
                val = _truncate(str(v), 60)
                lines.append(f"    in.{k}: {val}")
        if nt.outputs_summary:
            for k, v in nt.outputs_summary.items():
                val = _truncate(str(v), 60)
                lines.append(f"    out.{k}: {val}")
        if nt.error:
            lines.append(f"    ERROR: {nt.error[:80]}")
    lines.append("")
    lines.append(f"  Status: {trace.status}")
    if trace.started_at and trace.ended_at:
        lines.append(f"  Time: {trace.started_at} \u2192 {trace.ended_at}")
    return "\n".join(lines)


def format_nodes(glue: GlueGraph) -> str:
    """List all nodes in the graph."""
    lines = ["  Nodes:"]
    for node in glue.graph.nodes:
        skill = node.config.get("skill_id", node.op)
        lines.append(f"    {node.id}: {skill}")
    lines.append("  Outputs:")
    for name, addr in glue.graph.outputs.items():
        lines.append(f"    {name}: {addr}")
    return "\n".join(lines)


def _truncate(s: str, max_len: int) -> str:
    return s if len(s) <= max_len else s[:max_len - 3] + "..."


HELP_TEXT = """
  Commands:
    :help              Show this message
    :quit              Exit
    :history           Show previous goals
    :candidates        Show all candidates from last run
    :compare           Compare selected vs alternative
    :decomposition     Show last decomposition
    :rerun             Rerun last goal
    :rerun N           Rerun with N candidates
    :nodes             List graph nodes
    :graph             Export graph as ASCII/DOT
    :graph dot         Export as DOT format
    :trace             Show last execution trace
    :inspect <node>    Show node inputs/outputs from trace
    :refine <request>  Refine the current plan
    :delta             Show the last parsed delta
    :diff              Compare previous and current plan
    :plans             List plan versions in session
    :revert            Go back to previous plan version
    (anything else)    Plan a new goal
"""


# ── Session ────────────────────────────────────────────────────────


class InteractiveSession:
    """Manages state for an interactive planning session."""

    def __init__(
        self,
        backend: IRPlannerBackend,
        registry: Any,
        *,
        provider_name: str = "",
        model_name: str = "",
    ) -> None:
        self.backend = backend
        self.registry = registry
        self.provider_name = provider_name
        self.model_name = model_name
        self.history: list[str] = []
        self.last_result: PlanResult | None = None
        self.last_goal: str = ""
        self.last_trace: RunTrace | None = None
        # Plan versioning
        self.plan_versions: list[tuple[str, GlueGraph]] = []  # (label, graph)
        self.last_delta: Any = None  # RefinementRequest

    def run(self) -> None:
        cand_count = self.backend._candidate_count
        decomp = "on" if self.backend._use_decomposition else "off"
        typer.echo("")
        typer.secho("  Graphsmith Interactive", bold=True)
        typer.echo(f"  Provider: {self.provider_name} | Model: {self.model_name}")
        typer.echo(f"  Backend: IR ({cand_count} candidates, decomposition: {decomp})")
        typer.echo(f"  Type :help for commands")
        typer.echo("")

        while True:
            try:
                raw = input("  > ").strip()
            except (KeyboardInterrupt, EOFError):
                typer.echo("")
                break
            if not raw:
                continue
            if raw.startswith(":"):
                if not self._handle_command(raw):
                    break
            else:
                self._plan_goal(raw)

    def _handle_command(self, cmd: str) -> bool:
        parts = cmd.split(None, 1)
        name = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if name in (":quit", ":exit", ":q"):
            return False
        elif name == ":help":
            typer.echo(HELP_TEXT)
        elif name == ":history":
            self._show_history()
        elif name in (":candidates", ":cands"):
            self._show_candidates()
        elif name == ":compare":
            self._show_compare()
        elif name in (":decomposition", ":decomp"):
            self._show_decomposition()
        elif name == ":rerun":
            self._rerun(arg)
        elif name == ":nodes":
            self._show_nodes()
        elif name == ":graph":
            self._show_graph(arg)
        elif name == ":trace":
            self._show_trace()
        elif name == ":inspect":
            self._inspect_node(arg)
        elif name == ":refine":
            self._refine(arg)
        elif name == ":delta":
            self._show_delta()
        elif name == ":diff":
            self._show_diff()
        elif name == ":plans":
            self._show_plans()
        elif name == ":revert":
            self._revert()
        else:
            typer.echo(f"  Unknown command: {name}. Type :help")
        return True

    def _plan_goal(self, goal: str) -> None:
        self.last_goal = goal
        self.history.append(goal)
        self.last_trace = None

        typer.echo("  Planning...")
        typer.echo("")

        from graphsmith.planner.candidates import retrieve_candidates
        from graphsmith.planner.models import PlanRequest

        try:
            cands = retrieve_candidates(goal, self.registry)
            request = PlanRequest(goal=goal, candidates=cands)
            result = self.backend.compose(request)
        except Exception as exc:
            typer.secho(f"  Error: {exc}", fg=typer.colors.RED)
            typer.echo("")
            return

        self.last_result = result

        if result.status == "failure" or result.graph is None:
            typer.secho("  Planning failed.", fg=typer.colors.RED)
            if result.holes:
                for h in result.holes[:2]:
                    typer.echo(f"    {h.description[:120]}")
            typer.echo("")
            return

        # Record plan version
        label = f"v{len(self.plan_versions) + 1}: {goal[:40]}"
        self.plan_versions.append((label, result.graph))

        typer.echo(format_plan_summary(result.graph))

        compiled = [c for c in self.backend.last_candidates if c.status == "compiled"]
        typer.echo(f"\n  ({len(compiled)} candidates compiled, "
                   f":candidates to inspect, :refine to edit)")
        typer.echo("")

    def _show_history(self) -> None:
        if not self.history:
            typer.echo("  No goals yet.")
        else:
            typer.echo("  History:")
            for i, g in enumerate(self.history, 1):
                typer.echo(f"    {i}. {g}")
        typer.echo("")

    def _show_candidates(self) -> None:
        typer.echo(format_candidates(self.backend.last_candidates or []))

    def _show_compare(self) -> None:
        typer.echo(format_compare(self.backend.last_candidates or []))
        typer.echo("")

    def _show_decomposition(self) -> None:
        d = self.backend.last_decomposition
        if d is None:
            typer.echo("  No decomposition available.")
        else:
            typer.echo("  Decomposition:")
            typer.echo(f"    content_transforms: {d.content_transforms}")
            typer.echo(f"    presentation: {d.presentation}")
            typer.echo(f"    final_output_names: {d.final_output_names}")
            if d.reasoning:
                typer.echo(f"    reasoning: {d.reasoning[:120]}")
        typer.echo("")

    def _show_nodes(self) -> None:
        if not self.last_result or not self.last_result.graph:
            typer.echo("  No plan. Run a goal first.")
            return
        typer.echo(format_nodes(self.last_result.graph))
        typer.echo("")

    def _show_graph(self, fmt: str) -> None:
        if not self.last_result or not self.last_result.graph:
            typer.echo("  No plan. Run a goal first.")
            return
        from graphsmith.graph_export import graph_to_ascii, graph_to_dot
        if fmt.strip().lower() == "dot":
            typer.echo(graph_to_dot(self.last_result.graph))
        else:
            typer.echo(graph_to_ascii(self.last_result.graph))
        typer.echo("")

    def _show_trace(self) -> None:
        if self.last_trace:
            typer.echo(format_trace(self.last_trace))
            return
        # Execute the plan to produce a trace
        if not self.last_result or not self.last_result.graph:
            typer.echo("  No plan. Run a goal first.")
            return
        typer.echo("  (No execution trace yet — plan only. Execute with input to see traces.)")
        typer.echo("")

    def _inspect_node(self, node_id: str) -> None:
        node_id = node_id.strip()
        if not node_id:
            typer.echo("  Usage: :inspect <node_id>")
            return
        if not self.last_trace:
            typer.echo("  No trace. Execute a plan first to inspect nodes.")
            return
        for nt in self.last_trace.nodes:
            if nt.node_id == node_id:
                typer.echo(f"  Node: {nt.node_id} ({nt.op})")
                typer.echo(f"  Status: {nt.status}")
                if nt.inputs_summary:
                    typer.echo("  Inputs:")
                    for k, v in nt.inputs_summary.items():
                        typer.echo(f"    {k}: {_truncate(str(v), 80)}")
                if nt.outputs_summary:
                    typer.echo("  Outputs:")
                    for k, v in nt.outputs_summary.items():
                        typer.echo(f"    {k}: {_truncate(str(v), 80)}")
                if nt.error:
                    typer.echo(f"  Error: {nt.error}")
                typer.echo("")
                return
        typer.echo(f"  Node '{node_id}' not found in trace.")
        typer.echo("")

    def _rerun(self, arg: str) -> None:
        if not self.last_goal:
            typer.echo("  No previous goal to rerun.")
            return
        if arg.strip().isdigit():
            n = int(arg.strip())
            old = self.backend._candidate_count
            self.backend._candidate_count = n
            typer.echo(f"  Rerunning with {n} candidates...")
            self._plan_goal(self.last_goal)
            self.backend._candidate_count = old
        else:
            self._plan_goal(self.last_goal)

    # ── Refinement commands ───────────────────────────────────────

    def _refine(self, request: str) -> None:
        if not request.strip():
            try:
                request = input("  Refinement: ").strip()
            except (KeyboardInterrupt, EOFError):
                typer.echo("")
                return
        if not request:
            return

        if not self.last_goal or not self.last_result or not self.last_result.graph:
            typer.echo("  No plan to refine. Run a goal first.")
            return

        from graphsmith.planner.deltas import (
            build_refined_goal,
            compute_diff,
            extract_deltas,
            format_diff,
        )

        # Extract delta
        refinement = extract_deltas(request, self.last_result.graph)
        self.last_delta = refinement

        # Show extracted delta
        if refinement.deltas:
            for d in refinement.deltas:
                typer.echo(f"  Delta: {d.kind}({d.target})")
        else:
            typer.echo(f"  (treating as goal amendment)")
        typer.echo("")

        # Build refined goal and replan
        refined_goal = build_refined_goal(self.last_goal, refinement)
        prev_graph = self.last_result.graph

        typer.echo(f"  Refined goal: {refined_goal[:80]}")
        typer.echo("  Replanning...")
        typer.echo("")

        self._plan_goal(refined_goal)

        # Show diff if both plans exist
        if self.last_result and self.last_result.graph and prev_graph:
            diff = compute_diff(prev_graph, self.last_result.graph)
            typer.echo(format_diff(diff))
            typer.echo("")

    def _show_delta(self) -> None:
        if not self.last_delta:
            typer.echo("  No delta. Use :refine first.")
            return
        typer.echo("  Last refinement:")
        typer.echo(f"    Request: {self.last_delta.raw_request}")
        for d in self.last_delta.deltas:
            typer.echo(f"    {d.kind}: {d.target}")
            if d.replacement:
                typer.echo(f"      -> {d.replacement}")
        typer.echo("")

    def _show_diff(self) -> None:
        if len(self.plan_versions) < 2:
            typer.echo("  Need at least 2 plan versions for diff.")
            return
        from graphsmith.planner.deltas import compute_diff, format_diff
        _, prev = self.plan_versions[-2]
        _, curr = self.plan_versions[-1]
        diff = compute_diff(prev, curr)
        typer.echo(f"\n  {format_plan_summary(prev)}\n")
        typer.echo("  ----->")
        typer.echo(f"\n  {format_plan_summary(curr)}\n")
        typer.echo(format_diff(diff))
        typer.echo("")

    def _show_plans(self) -> None:
        if not self.plan_versions:
            typer.echo("  No plan versions yet.")
            return
        typer.echo("  Plan versions:")
        for i, (label, graph) in enumerate(self.plan_versions):
            current = " (current)" if i == len(self.plan_versions) - 1 else ""
            chain = _ARROW.join(n.id for n in graph.graph.nodes)
            typer.echo(f"    {i+1}. {label}{current}")
            typer.echo(f"       {chain}")
        typer.echo("")

    def _revert(self) -> None:
        if len(self.plan_versions) < 2:
            typer.echo("  No previous version to revert to.")
            return
        self.plan_versions.pop()
        label, graph = self.plan_versions[-1]
        # Reconstruct last_result
        from graphsmith.planner.models import PlanResult
        self.last_result = PlanResult(status="success", graph=graph)
        typer.echo(f"  Reverted to: {label}")
        typer.echo(format_plan_summary(graph))
        typer.echo("")
