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
from graphsmith.planner.ir import IRInput, IROutputRef, IRSource, IRStep, PlanningIR
from graphsmith.planner.ir_parser import IRParseError, parse_ir_block_output, parse_ir_output
from graphsmith.planner.ir_prompt import (
    build_ir_block_repair_context,
    build_ir_planning_context,
    get_ir_block_repair_system_message,
    get_ir_system_message,
)
from graphsmith.planner.repair import (
    infer_block_output_ports,
    normalize_ir_contracts,
    repair_ir_locally,
)
from graphsmith.planner.ir_scorer import ScoreBreakdown, score_candidate
from graphsmith.planner.models import GlueGraph, PlanRequest, PlanResult, UnresolvedHole
from graphsmith.registry.index import IndexEntry


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
        structural = _compose_structural_synthesized_reuse(request)
        if structural is not None:
            return structural

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

        glue, err, repairs = self._compile(ir, request)
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
            cand = self._process_one_candidate(prompt, request, i, decomp)
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
        request: PlanRequest,
        index: int,
        decomp: SemanticDecomposition | None,
    ) -> CandidateResult:
        """Process a single candidate: LLM → parse → compile → score."""
        raw, err = self._call_llm(prompt)
        if err:
            return CandidateResult(
                index=index, status="provider_error", error=str(err.description),
            )

        ir, err = self._parse(raw, request.goal)
        if err:
            return CandidateResult(
                index=index, status="parse_error", error=str(err.description),
            )

        glue, err, repairs = self._compile(ir, request)
        if err:
            return CandidateResult(
                index=index, status="compile_error", ir=ir, error=str(err.description),
            )

        score = score_candidate(ir, request.goal, decomposition=decomp)
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

    def _compile(
        self,
        ir: PlanningIR,
        request: PlanRequest,
    ) -> tuple[GlueGraph | None, UnresolvedHole | None, list[str]]:
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
            latest_error = exc
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
                except CompilerError as repaired_exc:
                    latest_error = repaired_exc
                    repair_actions = [
                        *repair_actions,
                        *[
                            f"{action.target}: {action.action}"
                            for action in repaired.actions
                        ],
                    ]
                    ir = repaired.ir
            regenerated_ir, regen_actions = self._regenerate_failed_block(
                ir, latest_error, request,
            )
            if regenerated_ir is not None:
                regen_normalized = normalize_ir_contracts(regenerated_ir)
                regen_repair_actions = [
                    *repair_actions,
                    *regen_actions,
                    *[
                        f"{action.target}: {action.action}"
                        for action in regen_normalized.actions
                    ],
                ]
                try:
                    glue = compile_ir(regen_normalized.ir)
                    return glue, None, regen_repair_actions
                except CompilerError:
                    pass
            return None, UnresolvedHole(
                node_id="(compiler)", kind="validation_error",
                description=f"Compiler error ({latest_error.phase}): {latest_error}",
            ), repair_actions

    def _regenerate_failed_block(
        self,
        ir: PlanningIR,
        error: CompilerError,
        request: PlanRequest,
    ) -> tuple[PlanningIR | None, list[str]]:
        block_name = str(error.details.get("block_name", ""))
        if not block_name:
            return None, []

        block = next((candidate for candidate in ir.blocks if candidate.name == block_name), None)
        if block is None or block.kind not in {"loop", "branch"}:
            return None, []

        prompt = build_ir_block_repair_context(
            request,
            ir=ir,
            block=block,
            error=error,
            required_outputs=infer_block_output_ports(ir, block.name),
        )
        raw, provider_error = self._call_llm(
            prompt, system=get_ir_block_repair_system_message(),
        )
        if provider_error is not None:
            return None, []

        try:
            repaired_block = parse_ir_block_output(raw)
        except IRParseError:
            return None, []

        if repaired_block.name != block.name or repaired_block.kind != block.kind:
            return None, []

        repaired_blocks = [
            repaired_block if candidate.name == block_name else candidate
            for candidate in ir.blocks
        ]
        return ir.model_copy(update={"blocks": repaired_blocks}), [
            f"block:{block_name}: regenerated {block.kind} block locally via LLM"
        ]


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


def _compose_structural_synthesized_reuse(request: PlanRequest) -> PlanResult | None:
    """Build a bounded IR plan from a reused synthesized workflow plus follow-up steps."""
    workflow = _find_matching_synth_workflow(request.candidates)
    if workflow is None:
        return None

    followups = _find_structural_followups(workflow, request.candidates)
    if not followups:
        return None

    ir = _build_structural_reuse_ir(request.goal, workflow, followups)
    try:
        glue = compile_ir(ir)
    except CompilerError:
        return None

    return PlanResult(
        status="success",
        graph=glue,
        reasoning=(
            "Deterministically composed a reused synthesized workflow "
            f"with {len(followups)} structural follow-up step(s)."
        ),
        candidates_considered=[f"{c.id}@{c.version}" for c in request.candidates],
        repair_actions=["planner-native synthesized reuse composition"],
    )


def _find_matching_synth_workflow(candidates: list[IndexEntry]) -> IndexEntry | None:
    required_tags = {
        "synthesized",
        "subgraph",
        "closed-loop",
        "validated",
        "workflow:file_transform_write_pytest",
    }
    for cand in candidates:
        tags = set(cand.tags)
        if not cand.id.startswith("synth."):
            continue
        if not required_tags.issubset(tags):
            continue
        if {"input_path", "output_path", "cwd"}.issubset(set(cand.input_names)):
            return cand
    return None


def _find_structural_followups(
    workflow: IndexEntry,
    candidates: list[IndexEntry],
) -> list[IndexEntry]:
    current_outputs = set(workflow.output_names)
    selected: list[IndexEntry] = []
    remaining = [cand for cand in candidates if cand.id != workflow.id]

    synth_region = _find_matching_followup(
        remaining,
        current_outputs=current_outputs,
        preferred_ids=set(),
        required_tag="region:format_output",
    )
    if synth_region is not None:
        selected.append(synth_region)
        current_outputs = set(synth_region.output_names)
        remaining = [cand for cand in remaining if cand.id != synth_region.id]

    direct_followup = _find_matching_followup(
        remaining,
        current_outputs=current_outputs,
        preferred_ids={"text.prefix_lines.v1", "text.contains.v1", "text.starts_with.v1"},
        required_tag="",
    )
    if direct_followup is not None:
        selected.append(direct_followup)
        current_outputs = set(direct_followup.output_names)
        remaining = [cand for cand in remaining if cand.id != direct_followup.id]

    assertion = _find_matching_followup(
        remaining,
        current_outputs=current_outputs,
        preferred_ids={"text.contains.v1", "text.starts_with.v1"},
        required_tag="",
    )
    if assertion is not None and all(c.id != assertion.id for c in selected):
        selected.append(assertion)

    return selected


def _find_matching_followup(
    candidates: list[IndexEntry],
    *,
    current_outputs: set[str],
    preferred_ids: set[str],
    required_tag: str,
) -> IndexEntry | None:
    for cand in candidates:
        if preferred_ids and cand.id not in preferred_ids:
            continue
        if required_tag and required_tag not in set(cand.tags):
            continue
        if any(_match_output_to_input(current_outputs, inp_name) is not None for inp_name in cand.input_names):
            return cand
    return None


def _build_structural_reuse_ir(
    goal: str,
    workflow: IndexEntry,
    followups: list[IndexEntry],
) -> PlanningIR:
    inputs = [
        IRInput(name="input_path", type="string"),
        IRInput(name="output_path", type="string"),
        IRInput(name="cwd", type="string"),
    ]
    steps = [
        IRStep(
            name="workflow",
            skill_id=workflow.id,
            version=workflow.version,
            sources={
                "input_path": IRSource(step="input", port="input_path"),
                "output_path": IRSource(step="input", port="output_path"),
                "cwd": IRSource(step="input", port="cwd"),
            },
        )
    ]
    current_step = "workflow"
    current_outputs = set(workflow.output_names)
    all_effects = set(workflow.effects)
    seen_inputs = {field.name for field in inputs}

    for index, followup in enumerate(followups, start=1):
        sources: dict[str, IRSource] = {}
        for inp_name in followup.input_names:
            matched = _match_output_to_input(current_outputs, inp_name)
            if matched is not None:
                sources[inp_name] = IRSource(step=current_step, port=matched)
            else:
                if inp_name not in seen_inputs:
                    inputs.append(IRInput(name=inp_name, type="string"))
                    seen_inputs.add(inp_name)
                sources[inp_name] = IRSource(step="input", port=inp_name)

        step_name = f"followup_{index}"
        steps.append(
            IRStep(
                name=step_name,
                skill_id=followup.id,
                version=followup.version,
                sources=sources,
            )
        )
        current_step = step_name
        current_outputs = set(followup.output_names)
        all_effects.update(followup.effects)

    final_output_port = sorted(current_outputs)[0]
    return PlanningIR(
        goal=goal,
        inputs=inputs,
        steps=steps,
        final_outputs={final_output_port: IROutputRef(step=current_step, port=final_output_port)},
        effects=sorted(all_effects) or ["pure"],
    )


def _match_output_to_input(outputs: set[str], input_name: str) -> str | None:
    if input_name in outputs:
        return input_name
    alias_sources = {
        "text": ["stdout", "result", "normalized", "summary", "formatted", "prefixed"],
        "stdout": ["stdout", "formatted", "prefixed"],
        "lines": ["keywords"],
    }
    for source in alias_sources.get(input_name, []):
        if source in outputs:
            return source
    return None
