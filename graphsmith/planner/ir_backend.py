"""IR-based planner backend — LLM emits IR, compiler lowers to graph."""
from __future__ import annotations

from pydantic import BaseModel, Field

from graphsmith.exceptions import ProviderError
from graphsmith.ops.llm_provider import LLMProvider
from graphsmith.planner.compiler import CompilerError, compile_ir
from graphsmith.planner.decomposition import (
    DecompositionParseError,
    SemanticDecomposition,
    build_decomposition_prompt,
    decompose_deterministic,
    get_decomp_system_message,
    parse_decomposition,
)
from graphsmith.planner.ir import PlanningIR
from graphsmith.planner.ir_parser import IRParseError, parse_ir_output
from graphsmith.planner.ir_prompt import build_ir_planning_context, get_ir_system_message
from graphsmith.planner.repair import normalize_ir_contracts, repair_ir_locally
from graphsmith.planner.ir_scorer import ScoreBreakdown, score_candidate
from graphsmith.planner.models import GlueGraph, PlanRequest, PlanResult, UnresolvedHole


class CandidateResult(BaseModel):
    """Result of processing one IR candidate."""

    index: int
    status: str  # "compiled", "parse_error", "compile_error", "provider_error"
    ir: PlanningIR | None = None
    glue: GlueGraph | None = None
    score: ScoreBreakdown | None = None
    error: str = ""
    repairs: list[str] = Field(default_factory=list)


class IRPlannerBackend:
    """Planner backend that uses the IR pipeline.

    Pipeline: prompt → LLM → IR parse → compile → GlueGraph

    With candidate_count > 1, generates multiple candidates and selects
    the best one using deterministic semantic scoring.

    With use_decomposition=True, adds a decomposition stage:
    decompose → condition IR prompt → generate → compile → score
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        candidate_count: int = 1,
        use_decomposition: bool = False,
    ) -> None:
        self._provider = provider
        self._candidate_count = max(1, candidate_count)
        self._use_decomposition = use_decomposition
        self._last_candidates: list[CandidateResult] = []
        self._last_decomposition: SemanticDecomposition | None = None

    @property
    def last_candidates(self) -> list[CandidateResult]:
        """Access candidate details from the most recent compose() call."""
        return self._last_candidates

    @property
    def last_decomposition(self) -> SemanticDecomposition | None:
        """Access decomposition from the most recent compose() call."""
        return self._last_decomposition

    def compose(self, request: PlanRequest) -> PlanResult:
        # Get decomposition if enabled
        decomp: SemanticDecomposition | None = None
        if self._use_decomposition:
            decomp = self._get_decomposition(request)
        self._last_decomposition = decomp

        if self._candidate_count <= 1:
            return self._compose_single(request, decomp)
        return self._compose_reranked(request, decomp)

    def _get_decomposition(self, request: PlanRequest) -> SemanticDecomposition:
        """Get semantic decomposition — LLM with deterministic fallback."""
        prompt = build_decomposition_prompt(request)
        raw, err = self._call_llm(prompt, system=get_decomp_system_message())
        if err:
            return decompose_deterministic(request.goal)
        try:
            return parse_decomposition(raw)
        except Exception:
            return decompose_deterministic(request.goal)

    def _compose_single(
        self, request: PlanRequest, decomp: SemanticDecomposition | None,
    ) -> PlanResult:
        """Single-candidate path."""
        self._last_candidates = []
        prompt = self._build_prompt(request, decomp)
        cand_ids = [f"{c.id}@{c.version}" for c in request.candidates]

        raw, err = self._call_llm(prompt)
        if err:
            return PlanResult(
                status="failure", holes=[err],
                reasoning="Provider error", candidates_considered=cand_ids,
            )

        ir, err = self._parse(raw, request.goal)
        if err:
            return PlanResult(
                status="failure", holes=[err],
                reasoning=f"Raw output: {raw[:200]}", candidates_considered=cand_ids,
            )

        glue, err, repairs = self._compile(ir)
        if err:
            return PlanResult(
                status="failure", holes=[err],
                reasoning=ir.reasoning, candidates_considered=cand_ids,
            )

        return PlanResult(
            status="success", graph=glue,
            reasoning=ir.reasoning, candidates_considered=cand_ids,
            repair_actions=repairs,
        )

    def _compose_reranked(
        self, request: PlanRequest, decomp: SemanticDecomposition | None,
    ) -> PlanResult:
        """Multi-candidate path: generate N, score, pick best."""
        prompt = self._build_prompt(request, decomp)
        cand_ids = [f"{c.id}@{c.version}" for c in request.candidates]
        candidates: list[CandidateResult] = []

        for i in range(self._candidate_count):
            cand = self._process_one_candidate(prompt, request.goal, i, decomp)
            candidates.append(cand)

        self._last_candidates = candidates

        valid = [c for c in candidates if c.status == "compiled" and c.glue is not None]

        if valid:
            best = max(valid, key=lambda c: c.score.total if c.score else 0.0)
            reasoning_parts = [best.ir.reasoning if best.ir else ""]
            if best.score:
                reasoning_parts.append(
                    f"Selected candidate {best.index + 1}/{len(candidates)} "
                    f"(score: {best.score.total:.1f})"
                )
            return PlanResult(
                status="success",
                graph=best.glue,
                reasoning=" | ".join(p for p in reasoning_parts if p),
                candidates_considered=cand_ids,
                repair_actions=best.repairs,
            )

        errors = [c.error for c in candidates if c.error]
        return PlanResult(
            status="failure",
            holes=[
                UnresolvedHole(
                    node_id="(ir_rerank)",
                    kind="validation_error",
                    description=(
                        f"All {len(candidates)} candidates failed. "
                        f"Errors: {'; '.join(errors[:3])}"
                    ),
                )
            ],
            reasoning=f"All {len(candidates)} candidates failed",
            candidates_considered=cand_ids,
        )

    def _build_prompt(
        self, request: PlanRequest, decomp: SemanticDecomposition | None,
    ) -> str:
        """Build IR prompt, optionally conditioned on decomposition."""
        base_prompt = build_ir_planning_context(request)
        if decomp is None:
            return base_prompt
        return base_prompt + _decomp_contract_section(decomp)

    def _process_one_candidate(
        self,
        prompt: str,
        goal: str,
        index: int,
        decomp: SemanticDecomposition | None,
    ) -> CandidateResult:
        """Process a single candidate: LLM → parse → compile → score."""
        raw, err = self._call_llm(prompt)
        if err:
            return CandidateResult(
                index=index, status="provider_error", error=str(err.description),
            )

        ir, err = self._parse(raw, goal)
        if err:
            return CandidateResult(
                index=index, status="parse_error", error=str(err.description),
            )

        glue, err, repairs = self._compile(ir)
        if err:
            return CandidateResult(
                index=index, status="compile_error", ir=ir, error=str(err.description),
            )

        score = score_candidate(ir, goal, decomposition=decomp)
        return CandidateResult(
            index=index,
            status="compiled",
            ir=ir,
            glue=glue,
            score=score,
            repairs=repairs,
        )

    # ── Helper methods ─────────────────────────────────────────────

    def _call_llm(
        self, prompt: str, *, system: str | None = None,
    ) -> tuple[str, UnresolvedHole | None]:
        """Call the LLM provider."""
        sys_msg = system or get_ir_system_message()
        try:
            raw = self._provider.generate(prompt, system=sys_msg, json_mode=True)
            return raw, None
        except ProviderError as exc:
            return "", UnresolvedHole(
                node_id="(provider)", kind="unsupported_op", description=str(exc),
            )
        except Exception as exc:
            return "", UnresolvedHole(
                node_id="(provider)", kind="unsupported_op",
                description=f"LLM provider call failed: {exc}",
            )

    def _parse(self, raw: str, goal: str) -> tuple[PlanningIR | None, UnresolvedHole | None]:
        try:
            ir = parse_ir_output(raw, goal=goal)
            return ir, None
        except IRParseError as exc:
            return None, UnresolvedHole(
                node_id="(ir_parser)", kind="validation_error",
                description=f"Failed to parse IR: {exc}",
            )

    def _compile(self, ir: PlanningIR) -> tuple[GlueGraph | None, UnresolvedHole | None, list[str]]:
        normalized = normalize_ir_contracts(ir)
        ir = normalized.ir
        repair_actions = [
            f"{action.target}: {action.action}"
            for action in normalized.actions
        ]
        try:
            glue = compile_ir(ir)
            return glue, None, repair_actions
        except CompilerError as exc:
            repaired = repair_ir_locally(ir, exc)
            if repaired.actions:
                try:
                    glue = compile_ir(repaired.ir)
                    return glue, None, [
                        *repair_actions,
                        *[
                            f"{action.target}: {action.action}"
                            for action in repaired.actions
                        ],
                    ]
                except CompilerError:
                    pass
            return None, UnresolvedHole(
                node_id="(compiler)", kind="validation_error",
                description=f"Compiler error ({exc.phase}): {exc}",
            ), repair_actions


def _decomp_contract_section(decomp: SemanticDecomposition) -> str:
    """Format a decomposition as a binding contract appended to the IR prompt."""
    lines = [
        "\n\n# SEMANTIC CONTRACT (binding — follow exactly)",
        "",
        "The goal has been decomposed. Your IR MUST follow this contract:",
        "",
        f"Content transforms: {decomp.content_transforms}",
        f"Presentation: {decomp.presentation}",
        f"Required final output names: {decomp.final_output_names}",
        "",
        "Rules:",
        "- Include exactly the content transforms listed above (in order).",
        "- If presentation is \"none\", do NOT add any formatting/presentation step.",
        "- If presentation is \"list\", add a text.join_lines.v1 step.",
        "- If presentation is \"header\", add a template.render step with the constant in config.template.",
        "- final_outputs keys MUST use the names listed above.",
    ]
    return "\n".join(lines)
