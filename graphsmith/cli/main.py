"""CLI entrypoint."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer

from graphsmith.exceptions import (
    ExecutionError,
    ParseError,
    PlannerError,
    ProviderError,
    RegistryError,
    ValidationError,
)
from graphsmith.parser import load_skill_package
from graphsmith.validator import validate_skill_package

def _version_callback(value: bool) -> None:
    if value:
        from graphsmith import __version__
        typer.echo(f"graphsmith {__version__}")
        raise typer.Exit()


app = typer.Typer(
    help="Graphsmith — semantic planner + compiler for graph-based AI workflows.",
    callback=lambda version: None,
)


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", "-V", help="Print version and exit.",
                                  callback=_version_callback, is_eager=True),
) -> None:
    """Graphsmith CLI."""


# ── version / list-ops ───────────────────────────────────────────────


@app.command()
def version() -> None:
    """Print Graphsmith version."""
    from graphsmith import __version__
    typer.echo(f"graphsmith {__version__}")


@app.command("list-ops")
def list_ops() -> None:
    """List all primitive ops supported in v1."""
    from graphsmith.constants import PRIMITIVE_OPS
    for op in sorted(PRIMITIVE_OPS):
        typer.echo(op)


@app.command("list-models")
def list_models(
    provider: str = typer.Option(
        ..., "--provider",
        help="Provider name: anthropic, openai.",
    ),
    model: Optional[str] = typer.Option(None, "--model", help="Ignored (for flag compat)."),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Base URL for openai."),
) -> None:
    """List available models for a provider (requires API key)."""
    from graphsmith.exceptions import ProviderError
    from graphsmith.ops.providers import ProviderConfigError, create_provider

    if provider == "echo":
        typer.echo("echo (test double — no real models)")
        return

    try:
        p = create_provider(provider, base_url=base_url)
    except ProviderConfigError as exc:
        typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if not hasattr(p, "list_models"):
        typer.secho(
            f"Provider '{provider}' does not support model listing.",
            fg=typer.colors.YELLOW, err=True,
        )
        raise typer.Exit(code=1)

    try:
        models = p.list_models()
    except ProviderError as exc:
        typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if not models:
        typer.echo("No models found.")
        return

    for m in sorted(models, key=lambda x: x.get("id", "")):
        mid = m["id"]
        name = m.get("name", "")
        if name and name != mid:
            typer.echo(f"{mid}  ({name})")
        else:
            typer.echo(mid)


# ── validate ─────────────────────────────────────────────────────────


@app.command()
def validate(path: str) -> None:
    """Validate a skill package directory."""
    try:
        pkg = load_skill_package(path)
        validate_skill_package(pkg)
    except (ParseError, ValidationError) as exc:
        typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.secho(
        f"OK: {pkg.skill.id} v{pkg.skill.version}", fg=typer.colors.GREEN
    )


# ── inspect ──────────────────────────────────────────────────────────


@app.command()
def inspect(path: str) -> None:
    """Parse a skill package and print a readable summary."""
    try:
        pkg = load_skill_package(path)
    except ParseError as exc:
        typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    summary = {
        "id": pkg.skill.id,
        "name": pkg.skill.name,
        "version": pkg.skill.version,
        "description": pkg.skill.description,
        "effects": pkg.skill.effects,
        "inputs": [
            {"name": f.name, "type": f.type, "required": f.required}
            for f in pkg.skill.inputs
        ],
        "outputs": [
            {"name": f.name, "type": f.type}
            for f in pkg.skill.outputs
        ],
        "tags": pkg.skill.tags,
        "dependencies": pkg.skill.dependencies,
        "node_count": len(pkg.graph.nodes),
        "edge_count": len(pkg.graph.edges),
        "nodes": [
            {"id": n.id, "op": n.op} for n in pkg.graph.nodes
        ],
        "example_count": len(pkg.examples.examples),
    }
    typer.echo(json.dumps(summary, indent=2))


# ── schema ───────────────────────────────────────────────────────────


@app.command()
def schema(
    model: str = typer.Argument(
        help="Model to export: skill, graph, examples"
    ),
) -> None:
    """Export JSON Schema for a Graphsmith model."""
    from graphsmith.models.graph import GraphBody
    from graphsmith.models.package import ExamplesFile
    from graphsmith.models.skill import SkillMetadata

    registry = {
        "skill": SkillMetadata,
        "graph": GraphBody,
        "examples": ExamplesFile,
    }
    cls = registry.get(model)
    if cls is None:
        typer.secho(
            f"Unknown model '{model}'. Choose from: {', '.join(sorted(registry))}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=1)
    typer.echo(json.dumps(cls.model_json_schema(), indent=2))


# ── run ──────────────────────────────────────────────────────────────


@app.command()
def run(
    path: str,
    input: Optional[str] = typer.Option(  # noqa: A002
        None, "--input", "-i",
        help="Input as inline JSON string.",
    ),
    input_file: Optional[str] = typer.Option(
        None, "--input-file", "-f",
        help="Path to a JSON file containing input.",
    ),
    trace: bool = typer.Option(
        False, "--trace",
        help="Print execution trace after outputs.",
    ),
    mock_llm: bool = typer.Option(
        False, "--mock-llm",
        help="Use an echo mock for LLM ops (for testing).",
    ),
    registry_root: Optional[str] = typer.Option(
        None, "--registry",
        help="Custom registry root (default: ~/.graphsmith/registry).",
    ),
    trace_root: Optional[str] = typer.Option(
        None, "--trace-root",
        help="Persist trace to this directory.",
    ),
) -> None:
    """Run a validated skill package."""
    from graphsmith.ops.llm_provider import EchoLLMProvider
    from graphsmith.registry import LocalRegistry
    from graphsmith.runtime import run_skill_package
    from graphsmith.traces import TraceStore

    inputs = _resolve_inputs(input, input_file)

    try:
        pkg = load_skill_package(path)
        validate_skill_package(pkg)
    except (ParseError, ValidationError) as exc:
        typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    llm_provider = EchoLLMProvider(prefix="") if mock_llm else None
    reg = LocalRegistry(registry_root) if registry_root else LocalRegistry()

    try:
        result = run_skill_package(
            pkg, inputs, llm_provider=llm_provider, registry=reg,
        )
    except (ExecutionError, NotImplementedError) as exc:
        typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    # Persist trace if requested
    if trace_root:
        store = TraceStore(trace_root)
        tid = store.save(result.trace)
        typer.secho(f"Trace saved: {tid}", fg=typer.colors.CYAN, err=True)

    typer.echo(json.dumps(result.outputs, indent=2))

    if trace:
        typer.echo("\n--- trace ---")
        typer.echo(json.dumps(result.trace.to_dict(), indent=2))


# ── publish ──────────────────────────────────────────────────────────


@app.command()
def publish(
    path: str,
    registry_root: Optional[str] = typer.Option(
        None, "--registry",
        help="Custom registry root (default: ~/.graphsmith/registry).",
    ),
) -> None:
    """Publish a validated skill package to the local registry."""
    from graphsmith.registry import LocalRegistry

    reg = LocalRegistry(registry_root) if registry_root else LocalRegistry()
    try:
        entry, warnings = reg.publish(path)
    except (ParseError, ValidationError, RegistryError) as exc:
        typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.secho(
        f"Published: {entry.id} v{entry.version}", fg=typer.colors.GREEN
    )
    for w in warnings:
        typer.secho(f"  Warning: {w}", fg=typer.colors.YELLOW, err=True)


# ── search ───────────────────────────────────────────────────────────


@app.command()
def search(
    query: str = typer.Argument("", help="Text to search for."),
    effect: Optional[str] = typer.Option(None, "--effect", help="Filter by effect."),
    tag: Optional[str] = typer.Option(None, "--tag", help="Filter by tag."),
    input_name: Optional[str] = typer.Option(None, "--input-name", help="Filter by input name."),
    output_name: Optional[str] = typer.Option(None, "--output-name", help="Filter by output name."),
    registry_root: Optional[str] = typer.Option(
        None, "--registry",
        help="Custom registry root (default: ~/.graphsmith/registry).",
    ),
) -> None:
    """Search published skills in the local registry."""
    from graphsmith.registry import LocalRegistry

    reg = LocalRegistry(registry_root) if registry_root else LocalRegistry()
    results = reg.search(
        query,
        effect=effect,
        tag=tag,
        input_name=input_name,
        output_name=output_name,
    )

    if not results:
        typer.echo("No results.")
        return

    typer.echo(json.dumps([e.to_dict() for e in results], indent=2))


# ── show ─────────────────────────────────────────────────────────────


@app.command()
def show(
    skill_id: str,
    version: str = typer.Option(..., "--version", "-v", help="Exact version."),
    registry_root: Optional[str] = typer.Option(
        None, "--registry",
        help="Custom registry root (default: ~/.graphsmith/registry).",
    ),
) -> None:
    """Show details of a published skill."""
    from graphsmith.registry import LocalRegistry

    reg = LocalRegistry(registry_root) if registry_root else LocalRegistry()
    try:
        pkg = reg.fetch(skill_id, version)
    except RegistryError as exc:
        typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    summary = {
        "id": pkg.skill.id,
        "name": pkg.skill.name,
        "version": pkg.skill.version,
        "description": pkg.skill.description,
        "effects": pkg.skill.effects,
        "inputs": [
            {"name": f.name, "type": f.type, "required": f.required}
            for f in pkg.skill.inputs
        ],
        "outputs": [
            {"name": f.name, "type": f.type}
            for f in pkg.skill.outputs
        ],
        "tags": pkg.skill.tags,
        "dependencies": pkg.skill.dependencies,
    }
    typer.echo(json.dumps(summary, indent=2))


# ── plan ─────────────────────────────────────────────────────────────


@app.command()
def plan(
    goal: str = typer.Argument(help="Natural-language goal for the plan."),
    registry_root: Optional[str] = typer.Option(
        None, "--registry",
        help="Custom registry root (default: ~/.graphsmith/registry).",
    ),
    max_candidates: int = typer.Option(
        20, "--max-candidates",
        help="Maximum candidate skills to consider.",
    ),
    output_format: str = typer.Option(
        "text", "--output-format",
        help="Output format: text or json.",
    ),
    show_retrieval: bool = typer.Option(
        False, "--show-retrieval",
        help="Show retrieval diagnostics in text output.",
    ),
    backend: str = typer.Option(
        "auto", "--backend",
        help="Planner backend: auto, mock, llm, or ir.",
    ),
    mock_llm: bool = typer.Option(
        False, "--mock-llm",
        help="Use echo mock as LLM provider for the llm backend.",
    ),
    provider: str = typer.Option(
        "echo", "--provider",
        help="LLM provider: echo, anthropic, openai.",
    ),
    model: Optional[str] = typer.Option(
        None, "--model",
        help="Model name for the LLM provider.",
    ),
    base_url: Optional[str] = typer.Option(
        None, "--base-url",
        help="Base URL for OpenAI-compatible provider.",
    ),
    save: Optional[str] = typer.Option(
        None, "--save",
        help="Save the plan to a JSON file (GlueGraph format).",
    ),
    save_on_failure: Optional[str] = typer.Option(
        None, "--save-on-failure",
        help="Save the full PlanResult JSON on failure for debugging.",
    ),
) -> None:
    """Plan a glue graph from a natural-language goal."""
    from graphsmith.planner import compose_plan, save_plan
    from graphsmith.registry import LocalRegistry

    reg = LocalRegistry(registry_root) if registry_root else LocalRegistry()
    planner_backend = _make_planner_backend(
        backend, mock_llm, provider=provider, model=model, base_url=base_url,
    )

    result = compose_plan(
        goal, reg, planner_backend, max_candidates=max_candidates,
    )

    # Save plan if requested and graph exists
    if save and result.graph:
        save_plan(result.graph, save)
        typer.secho(f"Plan saved: {save}", fg=typer.colors.CYAN, err=True)

    # Save on failure for debugging
    if save_on_failure and result.status != "success":
        Path(save_on_failure).write_text(
            json.dumps(result.model_dump(), indent=2) + "\n", encoding="utf-8",
        )
        typer.secho(f"Failed plan saved: {save_on_failure}", fg=typer.colors.CYAN, err=True)

    if output_format == "json":
        typer.echo(json.dumps(result.model_dump(), indent=2))
        return

    # Text output
    typer.echo(f"Goal: {result.graph.goal if result.graph else goal}")
    typer.echo(f"Status: {result.status}")
    typer.echo(f"Reasoning: {result.reasoning}")

    if result.candidates_considered:
        typer.echo(f"\nCandidates considered ({len(result.candidates_considered)}):")
        for c in result.candidates_considered:
            typer.echo(f"  - {c}")

    if result.repair_actions:
        typer.echo(f"\nRepairs applied ({len(result.repair_actions)}):")
        for action in result.repair_actions:
            typer.echo(f"  - {action}")

    if show_retrieval and result.retrieval:
        typer.echo(
            f"\nRetrieval [{result.retrieval.mode}] "
            f"({result.retrieval.candidate_count} candidates):"
        )
        typer.echo(f"  Registry size: {result.retrieval.registry_size}")
        if result.retrieval.empty_registry:
            typer.echo("  Registry is empty.")
        elif result.retrieval.fallback_used:
            typer.echo("  Fallback used: no positive lexical matches, returning registry entries.")
        if result.retrieval.raw_tokens:
            typer.echo(f"  Raw tokens: {', '.join(result.retrieval.raw_tokens)}")
        if result.retrieval.expanded_tokens:
            typer.echo(f"  Expanded tokens: {', '.join(result.retrieval.expanded_tokens)}")
        for skill_id in result.retrieval.candidates:
            score = result.retrieval.scores.get(skill_id)
            if score is None:
                typer.echo(f"  - {skill_id}")
            else:
                typer.echo(f"  - {skill_id} (score: {score})")

    if result.graph:
        g = result.graph
        typer.echo(f"\nInputs: {', '.join(f.name for f in g.inputs) or '(none)'}")
        typer.echo(f"Outputs: {', '.join(f.name for f in g.outputs) or '(none)'}")
        typer.echo(f"Effects: {', '.join(g.effects) or 'pure'}")
        typer.echo(f"Nodes ({len(g.graph.nodes)}):")
        for n in g.graph.nodes:
            typer.echo(f"  - {n.id}: {n.op}")

    if result.holes:
        typer.echo(f"\nUnresolved holes ({len(result.holes)}):")
        for h in result.holes:
            typer.echo(f"  [{h.kind}] {h.node_id}: {h.description}")
            if h.candidates:
                typer.echo(f"    candidates: {', '.join(h.candidates)}")

    if result.status == "failure":
        raise typer.Exit(code=1)


# ── plan-and-run ─────────────────────────────────────────────────────


@app.command("plan-and-run")
def plan_and_run(
    goal: str = typer.Argument(help="Natural-language goal."),
    input: Optional[str] = typer.Option(  # noqa: A002
        None, "--input", "-i", help="Input as inline JSON string.",
    ),
    input_file: Optional[str] = typer.Option(
        None, "--input-file", "-f", help="Path to a JSON file containing input.",
    ),
    registry_root: Optional[str] = typer.Option(
        None, "--registry", help="Custom registry root.",
    ),
    backend: str = typer.Option("auto", "--backend", help="Planner backend: auto, mock, llm, or ir."),
    mock_llm: bool = typer.Option(False, "--mock-llm", help="Use echo mock for LLM ops."),
    provider: str = typer.Option("echo", "--provider", help="LLM provider: echo, anthropic, openai."),
    model: Optional[str] = typer.Option(None, "--model", help="Model name."),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Base URL for openai provider."),
    trace_root: Optional[str] = typer.Option(None, "--trace-root", help="Persist trace."),
    trace: bool = typer.Option(False, "--trace", help="Print trace after outputs."),
    output_format: str = typer.Option("text", "--output-format", help="Output format: text or json."),
    save_on_failure: Optional[str] = typer.Option(
        None, "--save-on-failure",
        help="Save the full PlanResult JSON on failure for debugging.",
    ),
) -> None:
    """Plan a glue graph and execute it in one step."""
    from graphsmith.ops.llm_provider import EchoLLMProvider
    from graphsmith.planner import compose_plan, run_glue_graph
    from graphsmith.registry import LocalRegistry
    from graphsmith.traces import TraceStore

    inputs = _resolve_inputs(input, input_file)
    reg = LocalRegistry(registry_root) if registry_root else LocalRegistry()
    planner_backend = _make_planner_backend(
        backend, mock_llm, provider=provider, model=model, base_url=base_url,
    )
    llm_provider = _make_execution_provider(
        mock_llm,
        provider=provider,
        model=model,
        base_url=base_url,
    )

    # 1. Plan
    result = compose_plan(goal, reg, planner_backend)

    if result.status != "success":
        if save_on_failure:
            Path(save_on_failure).write_text(
                json.dumps(result.model_dump(), indent=2) + "\n", encoding="utf-8",
            )
            typer.secho(f"Failed plan saved: {save_on_failure}", fg=typer.colors.CYAN, err=True)
        _print_plan_problems(result, goal)
        raise typer.Exit(code=1)

    assert result.graph is not None

    # 2. Execute
    try:
        exec_result = run_glue_graph(
            result.graph, inputs, llm_provider=llm_provider, registry=reg,
        )
    except (ExecutionError, PlannerError) as exc:
        typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    # 3. Persist trace
    if trace_root:
        store = TraceStore(trace_root)
        tid = store.save(exec_result.trace)
        typer.secho(f"Trace saved: {tid}", fg=typer.colors.CYAN, err=True)

    # 4. Output
    if output_format == "json":
        out = {
            "plan": {"goal": result.graph.goal, "status": result.status},
            "outputs": exec_result.outputs,
        }
        if getattr(exec_result, "repairs", None):
            out["runtime_repairs"] = exec_result.repairs
        typer.echo(json.dumps(out, indent=2))
    else:
        typer.echo(json.dumps(exec_result.outputs, indent=2))
        if getattr(exec_result, "repairs", None):
            typer.echo("\nRuntime repairs:")
            for action in exec_result.repairs:
                typer.echo(f"  - {action}")

    if trace:
        typer.echo("\n--- trace ---")
        typer.echo(json.dumps(exec_result.trace.to_dict(), indent=2))


# ── run-plan ─────────────────────────────────────────────────────────


@app.command("run-plan")
def run_plan_cmd(
    path: str = typer.Argument(help="Path to a saved plan JSON file."),
    input: Optional[str] = typer.Option(  # noqa: A002
        None, "--input", "-i", help="Input as inline JSON string.",
    ),
    input_file: Optional[str] = typer.Option(
        None, "--input-file", "-f", help="Path to a JSON file containing input.",
    ),
    mock_llm: bool = typer.Option(False, "--mock-llm", help="Use echo mock for LLM ops."),
    registry_root: Optional[str] = typer.Option(None, "--registry", help="Custom registry root."),
    trace_root: Optional[str] = typer.Option(None, "--trace-root", help="Persist trace."),
    trace: bool = typer.Option(False, "--trace", help="Print trace after outputs."),
) -> None:
    """Run a previously saved plan."""
    from graphsmith.ops.llm_provider import EchoLLMProvider
    from graphsmith.planner import load_plan, run_glue_graph
    from graphsmith.registry import LocalRegistry
    from graphsmith.traces import TraceStore

    inputs = _resolve_inputs(input, input_file)
    llm_provider = EchoLLMProvider(prefix="") if mock_llm else None
    reg = LocalRegistry(registry_root) if registry_root else LocalRegistry()

    try:
        glue = load_plan(path)
    except PlannerError as exc:
        typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    try:
        result = run_glue_graph(
            glue, inputs, llm_provider=llm_provider, registry=reg,
        )
    except (ExecutionError, PlannerError) as exc:
        typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if trace_root:
        store = TraceStore(trace_root)
        tid = store.save(result.trace)
        typer.secho(f"Trace saved: {tid}", fg=typer.colors.CYAN, err=True)

    typer.echo(json.dumps(result.outputs, indent=2))

    if trace:
        typer.echo("\n--- trace ---")
        typer.echo(json.dumps(result.trace.to_dict(), indent=2))


# ── traces ───────────────────────────────────────────────────────────


@app.command("traces-list")
def traces_list(
    trace_root: Optional[str] = typer.Option(
        None, "--trace-root",
        help="Custom trace root (default: ~/.graphsmith/traces).",
    ),
    summary: bool = typer.Option(
        False, "--summary",
        help="Print one compact summary line per trace.",
    ),
) -> None:
    """List stored execution traces."""
    from graphsmith.traces import TraceStore

    store = TraceStore(trace_root) if trace_root else TraceStore()
    if summary:
        summaries = store.list_summaries()
        if not summaries:
            typer.echo("No traces found.")
            return
        for item in summaries:
            typer.echo(
                f"{item['trace_id']} | {item['skill_id']} | {item['status']} | "
                f"{item['node_count']} nodes | {item['op_signature']}"
            )
        return

    ids = store.list_ids()
    if not ids:
        typer.echo("No traces found.")
        return
    for tid in ids:
        typer.echo(tid)


@app.command("traces-show")
def traces_show(
    trace_id: str = typer.Argument(help="Trace ID to show."),
    trace_root: Optional[str] = typer.Option(
        None, "--trace-root",
        help="Custom trace root (default: ~/.graphsmith/traces).",
    ),
    summary: bool = typer.Option(
        False, "--summary",
        help="Print a compact summary instead of the full trace.",
    ),
) -> None:
    """Show a stored execution trace."""
    from graphsmith.traces import TraceStore

    store = TraceStore(trace_root) if trace_root else TraceStore()
    try:
        if summary:
            data = store.summarise(trace_id)
        else:
            data = store.load(trace_id)
    except FileNotFoundError:
        typer.secho(f"FAIL: Trace '{trace_id}' not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.echo(json.dumps(data, indent=2))


@app.command("traces-prune")
def traces_prune(
    older_than: int = typer.Option(
        ..., "--older-than",
        help="Remove traces older than this many days.",
    ),
    trace_root: Optional[str] = typer.Option(
        None, "--trace-root",
        help="Custom trace root (default: ~/.graphsmith/traces).",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Show what would be removed without deleting.",
    ),
) -> None:
    """Remove old traces."""
    from graphsmith.traces import TraceStore

    store = TraceStore(trace_root) if trace_root else TraceStore()
    removed = store.prune(older_than, dry_run=dry_run)

    if not removed:
        typer.echo("No traces to prune.")
        return

    verb = "Would remove" if dry_run else "Removed"
    typer.echo(f"{verb} {len(removed)} trace(s):")
    for tid in removed:
        typer.echo(f"  {tid}")


# ── promote-candidates ───────────────────────────────────────────────


@app.command("promote-candidates")
def promote_candidates(
    trace_root: Optional[str] = typer.Option(
        None, "--trace-root",
        help="Custom trace root (default: ~/.graphsmith/traces).",
    ),
    min_frequency: int = typer.Option(
        2, "--min-frequency",
        help="Minimum occurrences for a pattern to be a candidate.",
    ),
    output_format: str = typer.Option(
        "text", "--output-format",
        help="Output format: text or json.",
    ),
) -> None:
    """Find promotion candidates from stored traces."""
    from graphsmith.traces import TraceStore, find_promotion_candidates

    store = TraceStore(trace_root) if trace_root else TraceStore()
    candidates = find_promotion_candidates(store, min_frequency=min_frequency)

    if output_format == "json":
        typer.echo(json.dumps([c.model_dump() for c in candidates], indent=2))
        return

    if not candidates:
        typer.echo("No promotion candidates found.")
        return

    typer.echo(f"Promotion candidates ({len(candidates)}):\n")
    for c in candidates:
        typer.echo(f"  Signature: {c.signature}")
        if c.structural_signature and c.structural_signature != c.signature:
            typer.echo(f"  Structural: {c.structural_signature}")
        typer.echo(f"  Frequency: {c.frequency}")
        typer.echo(f"  Confidence: {c.confidence:.2f}")
        typer.echo(f"  Ops: {' -> '.join(c.ops)}")
        if c.suggested_skill_id:
            typer.echo(f"  Suggested skill: {c.suggested_skill_id}")
        if c.suggested_name:
            typer.echo(f"  Suggested name: {c.suggested_name}")
        typer.echo(f"  Traces: {', '.join(c.trace_ids[:5])}"
                   + (f" (+{len(c.trace_ids)-5} more)" if len(c.trace_ids) > 5 else ""))
        if c.inferred_inputs:
            typer.echo(f"  Inferred inputs: {', '.join(c.inferred_inputs)}")
        if c.inferred_outputs:
            typer.echo(f"  Inferred outputs: {', '.join(c.inferred_outputs)}")
        example_ids = c.trace_ids[:3]
        if example_ids:
            typer.echo(f"  Inspect examples:")
            for tid in example_ids:
                try:
                    summary = store.summarise(tid)
                    typer.echo(
                        f"    - {tid} | {summary['skill_id']} | "
                        f"{summary['status']} | {summary['node_count']} nodes"
                    )
                except FileNotFoundError:
                    typer.echo(f"    - {tid}")
        typer.echo(f"  Notes: {c.notes}")
        typer.echo()


@app.command("solve")
def solve(
    goal: str = typer.Argument(help="Natural-language goal to solve with closed-loop generation."),
    registry: Optional[str] = typer.Option(None, "--registry", help="Registry root with published skills."),
    backend: str = typer.Option("ir", "--backend", help="Planner backend: auto, mock, llm, or ir."),
    provider: str = typer.Option("echo", "--provider", help="LLM provider: echo, anthropic, openai, groq, or ollama."),
    model: Optional[str] = typer.Option(None, "--model", help="Model name override for supported providers."),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Base URL override for OpenAI-compatible providers."),
    mock_llm: bool = typer.Option(False, "--mock-llm", help="Use echo provider for planning/execution."),
    auto_approve: bool = typer.Option(False, "--auto-approve", help="Skip confirmation before replanning with a generated skill."),
    ir_candidates: int = typer.Option(1, "--ir-candidates", min=1, max=8, help="Number of IR candidates to generate and rerank."),
    use_decomposition: bool = typer.Option(False, "--decompose", help="Add semantic decomposition before IR generation."),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", help="Directory for generated skill files."),
) -> None:
    """Attempt bounded closed-loop missing-skill generation and replanning."""
    import tempfile

    from graphsmith.registry import LocalRegistry
    from graphsmith.skills.closed_loop import format_closed_loop_result, run_closed_loop

    reg = LocalRegistry(registry) if registry else LocalRegistry(Path(tempfile.mkdtemp()))
    planner_backend = _make_planner_backend(
        backend,
        mock_llm,
        provider=provider,
        model=model,
        base_url=base_url,
        ir_candidates=ir_candidates,
        use_decomposition=use_decomposition,
    )
    result = run_closed_loop(
        goal,
        planner_backend,
        reg,
        output_dir=output_dir,
        auto_approve=auto_approve,
    )
    typer.echo(format_closed_loop_result(result))


# ── ui ───────────────────────────────────────────────────────────────


@app.command()
def ui(
    port: int = typer.Option(8741, "--port", help="Local server port."),
) -> None:
    """Launch the local plan inspector UI in your browser."""
    import http.server
    import threading
    import webbrowser

    ui_dir = Path(__file__).resolve().parent.parent.parent / "ui"
    if not (ui_dir / "index.html").exists():
        typer.secho("FAIL: ui/index.html not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(ui_dir), **kwargs)
        def log_message(self, fmt: str, *args: Any) -> None:
            pass  # suppress request logs

    url = f"http://localhost:{port}"
    typer.echo(f"Graphsmith Inspector running at {url}")
    typer.echo("Press Ctrl+C to stop.\n")
    typer.echo(f"Open a plan: drag a JSON file onto the page, or use the file picker.")

    server = http.server.HTTPServer(("localhost", port), Handler)
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\nStopped.")
        server.shutdown()


# ── show-plan / render-plan ───────────────────────────────────────────


@app.command("show-plan")
def show_plan_cmd(
    path: str = typer.Argument(help="Path to a saved plan JSON file."),
) -> None:
    """Show a saved plan in human-readable format."""
    from graphsmith.planner import load_plan
    from graphsmith.planner.render import render_plan_text

    try:
        glue = load_plan(path)
    except PlannerError as exc:
        typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(render_plan_text(glue))


@app.command("render-plan")
def render_plan_cmd(
    path: str = typer.Argument(help="Path to a saved plan JSON file."),
    fmt: str = typer.Option("mermaid", "--format", help="Output format: mermaid or text."),
) -> None:
    """Render a saved plan as a Mermaid diagram or text."""
    from graphsmith.planner import load_plan
    from graphsmith.planner.render import render_plan_mermaid, render_plan_text

    try:
        glue = load_plan(path)
    except PlannerError as exc:
        typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if fmt == "mermaid":
        typer.echo(render_plan_mermaid(glue))
    else:
        typer.echo(render_plan_text(glue))


# ── eval-planner ─────────────────────────────────────────────────────


@app.command("eval-planner")
def eval_planner(
    goals_dir: str = typer.Option(
        "evaluation/goals", "--goals",
        help="Directory containing goal JSON files.",
    ),
    registry_root: Optional[str] = typer.Option(
        None, "--registry", help="Registry root with published skills.",
    ),
    backend: str = typer.Option("auto", "--backend", help="Planner backend: auto, mock, llm (direct graph), or ir (semantic IR + compiler + reranking)."),
    mock_llm: bool = typer.Option(False, "--mock-llm", help="Use echo mock for LLM."),
    provider: str = typer.Option("echo", "--provider", help="LLM provider: echo, anthropic, or openai (Groq/Ollama compatible)."),
    model: Optional[str] = typer.Option(None, "--model", help="Model name (e.g. claude-haiku-4-5-20251001, llama-3.1-8b-instant)."),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Base URL for OpenAI-compatible providers (e.g. https://api.groq.com/openai/v1)."),
    save_results: Optional[str] = typer.Option(
        None, "--save-results",
        help="Save results JSON to this path.",
    ),
    output_format: str = typer.Option("text", "--output-format", help="text or json."),
    retrieval_mode: str = typer.Option("ranked", "--retrieval-mode", help="Retrieval mode: ranked, broad, ranked_broad."),
    save_diagnostics: Optional[str] = typer.Option(None, "--save-diagnostics", help="Save per-goal diagnostics JSON."),
    compare_retrieval: bool = typer.Option(False, "--compare-retrieval", help="Compare all retrieval modes."),
    delay: float = typer.Option(0.0, "--delay", help="Seconds to wait between goals (rate-limit protection)."),
    save_failed_plans: Optional[str] = typer.Option(None, "--save-failed-plans", help="Save failed plan artifacts to this directory."),
    ir_candidates: int = typer.Option(1, "--ir-candidates", help="Number of IR candidates to generate and rerank. Use 3 for best results (IR backend only)."),
    use_decomposition: bool = typer.Option(False, "--decompose", help="Add semantic decomposition stage before IR generation. Improves planning quality (IR backend only)."),
) -> None:
    """Evaluate planner quality against a set of known goals.

    Recommended: --backend ir --ir-candidates 3 --decompose
    """
    from graphsmith.evaluation.planner_eval import compare_retrieval_modes, load_goals, run_evaluation
    from graphsmith.registry import LocalRegistry

    reg = LocalRegistry(registry_root) if registry_root else LocalRegistry()
    planner_backend = _make_planner_backend(
        backend, mock_llm, provider=provider, model=model, base_url=base_url,
        ir_candidates=ir_candidates, use_decomposition=use_decomposition,
    )

    goals = load_goals(goals_dir)
    if not goals:
        typer.secho("No goal files found.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1)

    prov_name = provider if backend in ("llm", "ir") else "mock"
    mod_name = model or ""

    if compare_retrieval:
        reports = compare_retrieval_modes(
            goals, reg, planner_backend,
            provider_name=prov_name, model_name=mod_name,
            delay_seconds=delay,
        )
        if save_results:
            Path(save_results).write_text(
                json.dumps({m: r.model_dump() for m, r in reports.items()}, indent=2) + "\n",
                encoding="utf-8",
            )
            typer.secho(f"Comparison saved: {save_results}", fg=typer.colors.CYAN, err=True)

        typer.echo(f"Retrieval Mode Comparison ({prov_name} {mod_name})")
        typer.echo("=" * 60)
        for mode, report in reports.items():
            typer.echo(f"  {mode:15s}  pass: {report.goals_passed}/{report.goals_total} = {report.pass_rate:.0%}  avg_cands: {report.avg_candidates}")
        return

    report = run_evaluation(
        goals, reg, planner_backend,
        provider_name=prov_name, model_name=mod_name,
        retrieval_mode=retrieval_mode,
        delay_seconds=delay,
    )

    if save_results:
        Path(save_results).write_text(
            json.dumps(report.model_dump(), indent=2) + "\n", encoding="utf-8",
        )
        typer.secho(f"Results saved: {save_results}", fg=typer.colors.CYAN, err=True)

    if save_diagnostics:
        diags = []
        for r in report.results:
            d: dict[str, Any] = {
                "goal": r.goal, "status": r.status,
                "failure_type": r.failure_type,
                "expected_in_shortlist": r.expected_skills_in_shortlist,
            }
            if r.retrieval:
                d["retrieval"] = r.retrieval.model_dump()
            if r.status != "pass":
                d["error"] = r.error
                d["holes"] = r.holes
                d["checks"] = r.checks.model_dump()
            diags.append(d)
        Path(save_diagnostics).write_text(
            json.dumps(diags, indent=2) + "\n", encoding="utf-8",
        )
        typer.secho(f"Diagnostics saved: {save_diagnostics}", fg=typer.colors.CYAN, err=True)

    if save_failed_plans:
        failed_dir = Path(save_failed_plans)
        failed_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for r in report.results:
            if r.status != "pass" and r.plan_json:
                slug = r.goal[:40].replace(" ", "_").replace("/", "_")
                fp = failed_dir / f"{slug}.json"
                fp.write_text(json.dumps({
                    "goal": r.goal,
                    "status": r.status,
                    "failure_type": r.failure_type,
                    "error": r.error,
                    "holes": r.holes,
                    "checks": r.checks.model_dump(),
                    "plan": r.plan_json,
                }, indent=2) + "\n", encoding="utf-8")
                count += 1
        typer.secho(f"Failed plans saved: {count} files in {save_failed_plans}", fg=typer.colors.CYAN, err=True)

    if output_format == "json":
        typer.echo(json.dumps(report.model_dump(), indent=2))
        return

    # Text output
    typer.echo(f"Planner Evaluation ({report.provider} {report.model}) [{report.retrieval_mode}]")
    typer.echo(f"{'=' * 60}")
    typer.echo(f"Goals: {report.goals_total}  Passed: {report.goals_passed}  "
               f"Rate: {report.pass_rate:.0%}  Avg candidates: {report.avg_candidates}\n")

    for r in report.results:
        icon = "pass" if r.status == "pass" else "PARTIAL" if r.status == "partial" else "FAIL"
        shortlist_ok = "Y" if r.expected_skills_in_shortlist else "N"
        cand_count = r.retrieval.candidate_count if r.retrieval else "?"
        typer.echo(f"  [{icon}] {r.goal}  (score: {r.score:.2f}, cands: {cand_count}, expected_in_list: {shortlist_ok})")
        if r.status != "pass":
            c = r.checks
            fails = []
            if not c.parsed:
                fails.append("parse failed")
            if not c.has_graph:
                fails.append("no graph")
            if not c.validates:
                fails.append("validation failed")
            if not c.correct_skills:
                fails.append("wrong skills")
            if not c.correct_outputs:
                fails.append("wrong outputs")
            if not c.min_nodes_met:
                fails.append("too few nodes")
            if not c.no_holes:
                fails.append("has holes")
            typer.echo(f"         issues: {', '.join(fails)}")
            if r.retrieval:
                typer.echo(f"         shortlist: {r.retrieval.candidates}")
            if r.error:
                typer.echo(f"         error: {r.error[:150]}")


# ── helpers ──────────────────────────────────────────────────────────


def _resolve_inputs(
    inline: str | None,
    file_path: str | None,
) -> dict:
    """Build the input dict from CLI options."""
    if inline and file_path:
        typer.secho(
            "FAIL: Provide either --input or --input-file, not both.",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)

    if inline:
        try:
            data = json.loads(inline)
        except json.JSONDecodeError as exc:
            typer.secho(
                f"FAIL: Invalid JSON in --input: {exc}",
                fg=typer.colors.RED, err=True,
            )
            raise typer.Exit(code=1) from exc
        if not isinstance(data, dict):
            typer.secho("FAIL: --input must be a JSON object",
                        fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        return data

    if file_path:
        p = Path(file_path)
        if not p.exists():
            typer.secho(f"FAIL: Input file not found: {file_path}",
                        fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            typer.secho(f"FAIL: Invalid JSON in {file_path}: {exc}",
                        fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
        if not isinstance(data, dict):
            typer.secho(f"FAIL: {file_path} must contain a JSON object",
                        fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        return data

    return {}


def _make_planner_backend(
    backend: str,
    mock_llm: bool,
    *,
    provider: str = "echo",
    model: str | None = None,
    base_url: str | None = None,
    ir_candidates: int = 1,
    use_decomposition: bool = False,
) -> Any:
    """Build a planner backend from CLI flags."""
    from graphsmith.planner import LLMPlannerBackend, MockPlannerBackend

    backend = _resolve_planner_backend_name(
        backend,
        mock_llm=mock_llm,
        provider=provider,
        model=model,
        base_url=base_url,
    )

    if backend not in ("llm", "ir"):
        return MockPlannerBackend()

    # Build the LLM provider
    if mock_llm:
        from graphsmith.ops.llm_provider import EchoLLMProvider
        llm = EchoLLMProvider(prefix="")
    else:
        from graphsmith.ops.providers import ProviderConfigError, create_provider
        try:
            llm = create_provider(provider, model=model, base_url=base_url)
        except (ProviderConfigError, ProviderError) as exc:
            typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc

    if backend == "ir":
        from graphsmith.planner.ir_backend import IRPlannerBackend
        return IRPlannerBackend(
            provider=llm,
            candidate_count=ir_candidates,
            use_decomposition=use_decomposition,
        )

    return LLMPlannerBackend(provider=llm)


def _resolve_planner_backend_name(
    backend: str,
    *,
    mock_llm: bool,
    provider: str,
    model: str | None,
    base_url: str | None,
) -> str:
    """Resolve the requested backend into a concrete implementation.

    `auto` preserves offline CLI ergonomics while preferring the IR path
    whenever the caller clearly intends model-backed planning.
    """
    if backend != "auto":
        return backend

    if mock_llm or provider != "echo" or model is not None or base_url is not None:
        return "ir"

    return "mock"


def _make_execution_provider(
    mock_llm: bool,
    *,
    provider: str = "echo",
    model: str | None = None,
    base_url: str | None = None,
) -> Any:
    """Build an execution-time LLM provider when the CLI requested one."""
    if mock_llm:
        from graphsmith.ops.llm_provider import EchoLLMProvider
        return EchoLLMProvider(prefix="")

    if provider == "echo" and model is None and base_url is None:
        return None

    from graphsmith.ops.providers import ProviderConfigError, create_provider
    try:
        return create_provider(provider, model=model, base_url=base_url)
    except (ProviderConfigError, ProviderError) as exc:
        typer.secho(f"FAIL: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


def _summarize_plan(glue: Any) -> str:
    """Format a GlueGraph as a human-readable plan summary."""
    lines = []
    lines.append("Plan Summary")
    lines.append("  Steps:")
    for i, node in enumerate(glue.graph.nodes, 1):
        skill = node.config.get("skill_id", node.op)
        lines.append(f"    {i}. {node.id} ({skill})")
    lines.append("  Outputs:")
    for name, addr in glue.graph.outputs.items():
        lines.append(f"    - {name} \u2190 {addr}")
    if glue.effects:
        lines.append(f"  Effects: {', '.join(glue.effects)}")
    return "\n  ".join(lines)
def _print_plan_problems(result: Any, goal: str) -> None:
    """Print plan failure/partial info to stderr."""
    typer.secho(
        f"Plan failed for goal: {goal} (status: {result.status})",
        fg=typer.colors.RED, err=True,
    )
    if result.reasoning:
        typer.echo(f"Reasoning: {result.reasoning}", err=True)
    for h in result.holes:
        typer.echo(f"  [{h.kind}] {h.node_id}: {h.description}", err=True)


if __name__ == "__main__":
    app()
