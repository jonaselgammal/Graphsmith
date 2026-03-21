"""Interactive planning session — inspect candidates, compare, iterate."""
from __future__ import annotations

from typing import Any

import typer

from graphsmith.planner.ir_backend import CandidateResult, IRPlannerBackend
from graphsmith.planner.models import PlanResult


# ── Formatting helpers ─────────────────────────────────────────────


def format_plan_summary(glue: Any) -> str:
    """Format a GlueGraph as a clean plan summary."""
    lines: list[str] = []
    lines.append("  Plan Summary")
    lines.append("  " + "-" * 40)
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
    """Format all candidates for inspection."""
    if not candidates:
        return "  No candidates available."
    lines: list[str] = []
    for c in candidates:
        selected = ""
        if c.glue is not None and c.score is not None:
            # Find if this was the winner (highest score among compiled)
            compiled = [x for x in candidates if x.status == "compiled" and x.score]
            if compiled:
                best = max(compiled, key=lambda x: x.score.total if x.score else 0)
                if c.index == best.index:
                    selected = " \u2714 SELECTED"

        lines.append(f"  Candidate {c.index + 1}:{selected}")
        if c.status != "compiled":
            lines.append(f"    status: {c.status}")
            if c.error:
                lines.append(f"    error: {c.error[:80]}")
        else:
            if c.ir:
                steps = " \u2192 ".join(s.name for s in c.ir.steps)
                lines.append(f"    steps: {steps}")
                outs = ", ".join(c.ir.final_outputs.keys())
                lines.append(f"    outputs: {outs}")
            if c.score:
                lines.append(f"    score: {c.score.total:.0f}")
                if c.score.penalties:
                    pens = [f"{r}" for r, _ in c.score.penalties[:3]]
                    lines.append(f"    penalties: {'; '.join(pens)}")
                if c.score.rewards:
                    rews = [f"{r}" for r, _ in c.score.rewards[:3]]
                    lines.append(f"    rewards: {'; '.join(rews)}")
        lines.append("")
    return "\n".join(lines)


def format_compare(candidates: list[CandidateResult]) -> str:
    """Compare selected candidate vs best alternative."""
    compiled = [c for c in candidates if c.status == "compiled" and c.score]
    if len(compiled) < 2:
        return "  Not enough candidates to compare."

    ranked = sorted(compiled, key=lambda c: c.score.total if c.score else 0, reverse=True)
    best = ranked[0]
    alternative = ranked[1]

    lines: list[str] = []
    lines.append("  Selected (Candidate {})".format(best.index + 1))
    if best.ir:
        lines.append("    steps: " + " \u2192 ".join(s.name for s in best.ir.steps))
        lines.append("    outputs: " + ", ".join(best.ir.final_outputs.keys()))
    lines.append(f"    score: {best.score.total:.0f}" if best.score else "")
    lines.append("")
    lines.append("  Alternative (Candidate {})".format(alternative.index + 1))
    if alternative.ir:
        lines.append("    steps: " + " \u2192 ".join(s.name for s in alternative.ir.steps))
        lines.append("    outputs: " + ", ".join(alternative.ir.final_outputs.keys()))
    lines.append(f"    score: {alternative.score.total:.0f}" if alternative.score else "")

    # Differences
    if best.ir and alternative.ir:
        best_skills = {s.skill_id for s in best.ir.steps}
        alt_skills = {s.skill_id for s in alternative.ir.steps}
        only_best = best_skills - alt_skills
        only_alt = alt_skills - best_skills
        lines.append("")
        lines.append("  Differences:")
        if only_best:
            lines.append(f"    selected has: {', '.join(sorted(only_best))}")
        if only_alt:
            lines.append(f"    alternative has: {', '.join(sorted(only_alt))}")
        if not only_best and not only_alt:
            lines.append("    same skills, different scores")
        if best.score and alternative.score:
            delta = best.score.total - alternative.score.total
            lines.append(f"    score delta: +{delta:.0f}")

    return "\n".join(lines)


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

    def run(self) -> None:
        """Main interactive loop."""
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
        """Handle a : command. Returns False to exit."""
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
        else:
            typer.echo(f"  Unknown command: {name}. Type :help")
        return True

    def _plan_goal(self, goal: str) -> None:
        """Plan a goal and display results."""
        self.last_goal = goal
        self.history.append(goal)

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

        typer.echo(format_plan_summary(result.graph))

        # Show brief candidate count
        compiled = [c for c in self.backend.last_candidates if c.status == "compiled"]
        typer.echo(f"\n  ({len(compiled)} candidates compiled, "
                   f":candidates to inspect, :compare to diff)")
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
        cands = self.backend.last_candidates
        if not cands:
            typer.echo("  No candidates. Run a goal first.")
        else:
            typer.echo(format_candidates(cands))

    def _show_compare(self) -> None:
        cands = self.backend.last_candidates
        if not cands:
            typer.echo("  No candidates. Run a goal first.")
        else:
            typer.echo(format_compare(cands))
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
