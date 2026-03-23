"""Live capability campaign — run tasks with real LLM planning."""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from graphsmith.evaluation.capability_ladder import (
    FAILURE_CATEGORIES,
    LadderTask,
    TaskResult,
    _outputs_match,
    load_ladder_tasks,
    summarize_results,
    format_report,
)


class LiveTaskResult(TaskResult):
    """Extended result with live-planning artifacts."""

    bucket: str = ""
    model: str = ""
    decomposition: dict[str, Any] = Field(default_factory=dict)
    candidate_count: int = 0
    plan_node_ids: list[str] = Field(default_factory=list)
    plan_outputs: dict[str, str] = Field(default_factory=dict)


def run_live_task(
    task: LadderTask,
    provider: str,
    model: str,
    *,
    base_url: str | None = None,
    delay: float = 2.0,
) -> LiveTaskResult:
    """Run a single task with live LLM planning."""
    from graphsmith.ops.providers import create_provider
    from graphsmith.parser import load_skill_package
    from graphsmith.planner.candidates import retrieve_candidates
    from graphsmith.planner.ir_backend import IRPlannerBackend
    from graphsmith.planner.models import PlanRequest
    from graphsmith.registry.local import LocalRegistry
    from graphsmith.skills.autogen import (
        AutogenError,
        extract_spec,
        generate_skill_files,
        register_generated_op,
        validate_and_test,
    )

    result = LiveTaskResult(
        task_id=task.id, level=task.level, goal=task.goal,
        bucket=getattr(task, "bucket", ""),
        model=model,
    )

    # Build registry
    reg_dir = tempfile.mkdtemp()
    reg = LocalRegistry(reg_dir)
    skills_dir = Path(__file__).resolve().parents[2] / "examples" / "skills"
    for d in sorted(skills_dir.iterdir()):
        if d.is_dir() and (d / "skill.yaml").exists():
            try:
                reg.publish(str(d))
            except Exception:
                pass

    # Closed-loop: generate missing skill if needed and allowed
    if task.closed_loop:
        try:
            spec = extract_spec(task.goal)
            gen_dir = Path(tempfile.mkdtemp())
            skill_dir = generate_skill_files(spec, gen_dir)
            val_result = validate_and_test(spec, skill_dir)
            if val_result["validation"] == "PASS" and val_result["examples_passed"] == val_result["examples_total"]:
                reg.publish(str(skill_dir))
                result.closed_loop_used = True
                result.generated_skill = spec.skill_id
        except AutogenError:
            pass  # no matching template, proceed without

    # Create LLM provider + backend
    try:
        llm = create_provider(provider, model=model, base_url=base_url)
    except Exception as exc:
        result.failure_category = "execution_error"
        result.error = f"Provider error: {exc}"
        return result

    backend = IRPlannerBackend(llm, candidate_count=3, use_decomposition=True)

    # Plan
    try:
        cands = retrieve_candidates(task.goal, reg)
        request = PlanRequest(goal=task.goal, candidates=cands)
        plan_result = backend.compose(request)
    except Exception as exc:
        result.failure_category = "execution_error"
        result.error = f"Planning error: {exc}"
        return result

    # Record decomposition
    if backend.last_decomposition:
        d = backend.last_decomposition
        result.decomposition = {
            "content_transforms": d.content_transforms,
            "presentation": d.presentation,
            "final_output_names": d.final_output_names,
        }

    result.candidate_count = len(backend.last_candidates)

    if plan_result.status != "success" or plan_result.graph is None:
        result.failure_category = "plan_failure"
        result.error = f"Plan status: {plan_result.status}"
        if plan_result.holes:
            result.error += f"; {plan_result.holes[0].description[:80]}"
        return result

    glue = plan_result.graph

    # Record plan shape
    result.plan_node_ids = [n.id for n in glue.graph.nodes]
    result.plan_skills = [n.config.get("skill_id", n.op) for n in glue.graph.nodes]
    result.plan_output_names = list(glue.graph.outputs.keys())
    result.plan_outputs = dict(glue.graph.outputs)

    # Check expected skills
    if task.expected_skills:
        plan_skill_set = set(result.plan_skills)
        if not all(s in plan_skill_set for s in task.expected_skills):
            result.failure_category = "wrong_skills"
            result.error = f"Expected {task.expected_skills}, got {result.plan_skills}"
            # Don't return — still check outputs

    # Check expected output names
    if task.expected_output_names:
        plan_outs = set(result.plan_output_names)
        # Check if at least one expected name is present
        if not any(name in plan_outs for name in task.expected_output_names):
            result.failure_category = "wrong_output_names"
            result.error = f"Expected one of {task.expected_output_names}, got {result.plan_output_names}"
            return result

    # If we have expected_output with concrete values, verify via execution
    if task.expected_output and len(task.expected_skills) == 1:
        from graphsmith.ops.registry import execute_op
        skill_id = task.expected_skills[0]
        op_name = skill_id.replace(".v1", "").replace(".v2", "")
        try:
            actual = execute_op(op_name, {}, task.input)
            result.actual_output = {k: str(v) for k, v in actual.items()}
            if _outputs_match(task.expected_output, result.actual_output, task.tolerance):
                result.status = "pass"
            else:
                if task.tolerance > 0:
                    result.failure_category = "numeric_mismatch"
                else:
                    result.failure_category = "wrong_output"
                result.error = f"Expected {task.expected_output}, got {result.actual_output}"
                return result
        except Exception as exc:
            result.failure_category = "execution_error"
            result.error = str(exc)
            return result
    else:
        # Structural pass: plan compiled, validated, correct shape
        if not result.failure_category:
            result.status = "pass"

    if delay > 0:
        time.sleep(delay)

    return result


def run_live_campaign(
    tasks: list[LadderTask],
    provider: str,
    model: str,
    *,
    base_url: str | None = None,
    delay: float = 2.0,
) -> list[LiveTaskResult]:
    """Run all tasks with live LLM planning."""
    results = []
    for i, task in enumerate(tasks):
        print(f"  [{i+1}/{len(tasks)}] {task.id}: {task.goal[:50]}...", flush=True)
        r = run_live_task(task, provider, model, base_url=base_url, delay=delay)
        mark = "\u2714" if r.status == "pass" else "\u2716"
        gen = f" [gen {r.generated_skill}]" if r.generated_skill else ""
        fail = f" ({r.failure_category})" if r.failure_category else ""
        print(f"    {mark}{gen}{fail}")
        results.append(r)
    return results


def summarize_by_bucket(results: list[LiveTaskResult]) -> dict[str, Any]:
    """Summarize results by bucket."""
    buckets: dict[str, list[LiveTaskResult]] = {}
    for r in results:
        buckets.setdefault(r.bucket or "?", []).append(r)

    summary: dict[str, Any] = {}
    for bucket in sorted(buckets):
        rs = buckets[bucket]
        passed = sum(1 for r in rs if r.status == "pass")
        summary[bucket] = {
            "total": len(rs),
            "passed": passed,
            "pass_rate": f"{passed}/{len(rs)}",
        }
    return summary


def format_live_report(results: list[LiveTaskResult]) -> str:
    """Format a human-readable live campaign report."""
    lines: list[str] = []
    total = len(results)
    passed = sum(1 for r in results if r.status == "pass")
    cl_used = sum(1 for r in results if r.closed_loop_used)
    cl_pass = sum(1 for r in results if r.closed_loop_used and r.status == "pass")

    lines.append("Live Capability Campaign Results")
    lines.append("=" * 50)
    lines.append(f"Total: {total}  Passed: {passed}  Failed: {total - passed}")
    lines.append(f"Closed-loop: {cl_used} used, {cl_pass} succeeded")
    if results:
        lines.append(f"Model: {results[0].model}")
    lines.append("")

    bucket_summary = summarize_by_bucket(results)
    for bucket, info in bucket_summary.items():
        lines.append(f"Bucket {bucket}: {info['pass_rate']} pass")
        for r in results:
            if (r.bucket or "?") == bucket:
                mark = "\u2714" if r.status == "pass" else "\u2716"
                gen = f" [gen {r.generated_skill}]" if r.generated_skill else ""
                lines.append(f"  {mark} {r.task_id}: {r.goal[:55]}{gen}")
                if r.failure_category:
                    lines.append(f"      {r.failure_category}: {r.error[:60]}")
        lines.append("")

    # Failure summary
    failures = {}
    for r in results:
        if r.failure_category:
            failures[r.failure_category] = failures.get(r.failure_category, 0) + 1
    if failures:
        lines.append("Failure categories:")
        for cat, count in sorted(failures.items()):
            lines.append(f"  {cat}: {count}")

    return "\n".join(lines)
