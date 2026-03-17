"""LLM-backed planner backend — parses raw provider output into typed PlanResult."""
from __future__ import annotations

from typing import Any

from graphsmith.exceptions import ProviderError
from graphsmith.ops.llm_provider import LLMProvider
from graphsmith.planner.models import PlanRequest, PlanResult, UnresolvedHole
from graphsmith.planner.parser import parse_planner_output
from graphsmith.planner.prompt import build_planning_context, get_system_message


class LLMPlannerBackend:
    """Planner backend that delegates to an LLM provider.

    1. Builds a structured prompt from the PlanRequest.
    2. Sends the prompt to the provider with system message and JSON hints.
    3. Parses the raw response into a typed PlanResult.
    """

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def compose(self, request: PlanRequest) -> PlanResult:
        prompt = build_planning_context(request)

        try:
            raw_response = self._provider.generate(
                prompt,
                system=get_system_message(),
                json_mode=True,
            )
        except ProviderError as exc:
            # Surface actionable provider errors (model not found, auth, etc.)
            return PlanResult(
                status="failure",
                holes=[
                    UnresolvedHole(
                        node_id="(provider)",
                        kind="unsupported_op",
                        description=str(exc),
                    )
                ],
                reasoning=f"Provider error: {exc}",
                candidates_considered=[
                    f"{c.id}@{c.version}" for c in request.candidates
                ],
            )
        except Exception as exc:
            return PlanResult(
                status="failure",
                holes=[
                    UnresolvedHole(
                        node_id="(provider)",
                        kind="unsupported_op",
                        description=f"LLM provider call failed: {exc}",
                    )
                ],
                reasoning=f"Provider error: {exc}",
                candidates_considered=[
                    f"{c.id}@{c.version}" for c in request.candidates
                ],
            )

        result = parse_planner_output(raw_response, goal=request.goal)
        result.candidates_considered = [
            f"{c.id}@{c.version}" for c in request.candidates
        ]
        return result
