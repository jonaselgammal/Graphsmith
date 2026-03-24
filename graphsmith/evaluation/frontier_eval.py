"""Frontier evaluation runner for closed-loop generalization probes."""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from graphsmith.registry.local import LocalRegistry
from graphsmith.skills.closed_loop import run_closed_loop


class FrontierCase(BaseModel):
    id: str
    goal: str
    tier: int = 1
    tags: list[str] = Field(default_factory=list)
    expected_success: bool = True
    accepted_stop_reasons: list[str] = Field(default_factory=list)
    notes: str = ""


class FrontierCaseResult(BaseModel):
    id: str
    goal: str
    tier: int
    status: str = "fail"
    expected_success: bool = True
    observed_success: bool = False
    initial_status: str = ""
    detected_missing: bool = False
    generated_skill_id: str = ""
    replan_status: str = ""
    stopped_reason: str = ""
    notes: str = ""


class FrontierReport(BaseModel):
    provider: str = ""
    model: str = ""
    timestamp: str = ""
    total: int = 0
    passed: int = 0
    pass_rate: float = 0.0
    results: list[FrontierCaseResult] = Field(default_factory=list)


def load_frontier_cases(goals_dir: str | Path) -> list[FrontierCase]:
    root = Path(goals_dir)
    return [
        FrontierCase.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(root.glob("*.json"))
    ]


def evaluate_frontier_case(
    case: FrontierCase,
    registry: LocalRegistry,
    backend: object,
) -> FrontierCaseResult:
    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as regdir:
        base_root = registry.root
        if base_root.exists():
            shutil.copytree(base_root, regdir, dirs_exist_ok=True)
        case_registry = LocalRegistry(regdir)
        result = run_closed_loop(
            case.goal,
            backend,
            case_registry,
            output_dir=tmpdir,
            auto_approve=True,
        )

    passed = result.success == case.expected_success
    if (
        not case.expected_success
        and case.accepted_stop_reasons
        and result.stopped_reason not in case.accepted_stop_reasons
    ):
        passed = False

    return FrontierCaseResult(
        id=case.id,
        goal=case.goal,
        tier=case.tier,
        status="pass" if passed else "fail",
        expected_success=case.expected_success,
        observed_success=bool(result.success),
        initial_status=result.initial_status,
        detected_missing=result.detected_missing,
        generated_skill_id=result.generated_spec.skill_id if result.generated_spec else "",
        replan_status=result.replan_status,
        stopped_reason=result.stopped_reason,
        notes=case.notes,
    )


def run_frontier_suite(
    cases: list[FrontierCase],
    registry: LocalRegistry,
    backend: object,
    *,
    provider_name: str = "",
    model_name: str = "",
) -> FrontierReport:
    results = [evaluate_frontier_case(case, registry, backend) for case in cases]
    total = len(results)
    passed = sum(1 for result in results if result.status == "pass")
    return FrontierReport(
        provider=provider_name,
        model=model_name,
        timestamp=datetime.now(timezone.utc).isoformat(),
        total=total,
        passed=passed,
        pass_rate=(passed / total) if total else 0.0,
        results=results,
    )
