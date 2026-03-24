"""Parse raw LLM output into typed PlanningIR."""
from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from graphsmith.planner.ir import (
    IRBinding,
    IRBlock,
    IRInput,
    IROutputRef,
    IRSource,
    IRStep,
    PlanningIR,
)
from graphsmith.planner.parser import _extract_json_text

_IR_REQUIRED_KEYS = {"inputs", "steps", "final_outputs"}


class IRParseError(Exception):
    """Failed to parse LLM output into PlanningIR."""

    def __init__(self, message: str, *, raw_snippet: str = "") -> None:
        self.raw_snippet = raw_snippet
        super().__init__(message)


def parse_ir_output(raw: str, *, goal: str) -> PlanningIR:
    """Parse raw LLM text into a typed PlanningIR.

    Uses the same JSON extraction logic as the direct parser
    (code fences, balanced braces).

    Raises IRParseError on any parsing failure.
    """
    text = _extract_json_text(raw)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IRParseError(
            f"Invalid JSON in planner output: {exc}",
            raw_snippet=raw[:500],
        ) from exc

    if not isinstance(data, dict):
        raise IRParseError(
            f"Expected JSON object, got {type(data).__name__}",
            raw_snippet=raw[:500],
        )

    missing = _IR_REQUIRED_KEYS - set(data.keys())
    if missing:
        raise IRParseError(
            f"Missing required keys: {', '.join(sorted(missing))}",
            raw_snippet=raw[:500],
        )

    try:
        return _build_ir(data, goal=goal)
    except (KeyError, TypeError, ValueError) as exc:
        raise IRParseError(
            f"Failed to build IR from parsed data: {exc}",
            raw_snippet=raw[:500],
        ) from exc


def _build_ir(data: dict[str, Any], *, goal: str) -> PlanningIR:
    """Construct a PlanningIR from parsed JSON data."""
    inputs = [
        IRInput(name=inp["name"], type=inp.get("type", "string"))
        for inp in data["inputs"]
    ]

    bindings = [
        IRBinding(
            name=binding["name"],
            source=_normalize_source(binding["source"]),
            description=binding.get("description", ""),
        )
        for binding in data.get("bindings", [])
    ]

    steps: list[IRStep] = []
    step_names: set[str] = set()
    for s in data["steps"]:
        sources: dict[str, IRSource] = {}
        for port, src in s.get("sources", {}).items():
            sources[port] = _normalize_source(src)
        name = s["name"]
        step_names.add(name)
        steps.append(
            IRStep(
                name=name,
                skill_id=s["skill_id"],
                version=s.get("version", "1.0.0"),
                sources=sources,
                config=s.get("config", {}),
                when=_normalize_source(s["when"]) if "when" in s else None,
                unless=bool(s.get("unless", False)),
            )
        )

    blocks: list[IRBlock] = []
    for block in data.get("blocks", []):
        block_steps: list[IRStep] = []
        block_step_names: set[str] = set()
        for step in block.get("steps", []):
            step_sources = {
                port: _normalize_source(src)
                for port, src in step.get("sources", {}).items()
            }
            block_step_names.add(step["name"])
            block_steps.append(
                IRStep(
                    name=step["name"],
                    skill_id=step["skill_id"],
                    version=step.get("version", "1.0.0"),
                    sources=step_sources,
                    config=step.get("config", {}),
                    when=_normalize_source(step["when"]) if "when" in step else None,
                    unless=bool(step.get("unless", False)),
                )
            )
        blocks.append(
            IRBlock(
                name=block["name"],
                kind=block["kind"],
                collection=_normalize_source(block["collection"]) if "collection" in block else None,
                inputs={
                    port: _normalize_source(src)
                    for port, src in block.get("inputs", {}).items()
                },
                steps=block_steps,
                final_outputs=_normalize_final_outputs(
                    block.get("final_outputs", {}),
                    block_step_names,
                ),
                max_items=int(block.get("max_items", 100)),
                config=block.get("config", {}),
            )
        )

    final_outputs = _normalize_final_outputs(data["final_outputs"], step_names)

    effects = data.get("effects", ["pure"])
    reasoning = data.get("reasoning", "")

    return PlanningIR(
        goal=goal,
        inputs=inputs,
        bindings=bindings,
        steps=steps,
        blocks=blocks,
        final_outputs=final_outputs,
        effects=effects,
        reasoning=reasoning,
    )


def _normalize_source(src: Any, step_names: set[str] | None = None) -> IRSource:
    """Normalize a source value into an IRSource.

    Accepts:
    - {"step": "...", "port": "..."} (canonical)
    - {"binding": "..."} (named value alias)
    - "step_name.port_name" (shorthand string)
    - "$binding_name" (binding shorthand)
    """
    if isinstance(src, dict):
        if "binding" in src:
            return IRSource(binding=src["binding"])
        return IRSource(step=src["step"], port=src["port"])

    if isinstance(src, str) and src.startswith("$") and len(src) > 1:
        return IRSource(binding=src[1:])

    if isinstance(src, str) and "." in src:
        parts = src.split(".", 1)
        return IRSource(step=parts[0], port=parts[1])

    raise ValueError(
        f"Invalid source format: expected object or 'step.port' string, got {src!r}"
    )


def _normalize_final_outputs(
    raw: Any,
    step_names: set[str],
) -> dict[str, IROutputRef]:
    """Normalize final_outputs from various LLM formats.

    Accepts:
    - {"name": {"step": "...", "port": "..."}} (canonical)
    - {"name": "step_name.port_name"} (shorthand string)
    - {"name": "step_name"} (bare step name — uses step name as port, only if unambiguous)
    """
    if not isinstance(raw, dict):
        raise ValueError(f"final_outputs must be an object, got {type(raw).__name__}")

    result: dict[str, IROutputRef] = {}
    for name, ref in raw.items():
        if isinstance(ref, dict):
            result[name] = IROutputRef(step=ref["step"], port=ref["port"])
        elif isinstance(ref, str):
            result[name] = _parse_output_ref_string(ref, name, step_names)
        else:
            raise ValueError(
                f"final_outputs['{name}']: expected object or string, got {type(ref).__name__}"
            )
    return result


def _parse_output_ref_string(
    ref: str,
    output_name: str,
    step_names: set[str],
) -> IROutputRef:
    """Parse a string-format output reference.

    Handles:
    - "step_name.port" → IROutputRef(step="step_name", port="port")
    - "step_name" (bare) → IROutputRef(step="step_name", port=output_name)

    When the string contains dots, tries to match the longest prefix that is
    a known step name (handles step names like "text.summarize").
    """
    if "." in ref:
        # Try longest-prefix match against known step names first
        best_step = ""
        for name in step_names:
            if ref.startswith(name + ".") and len(name) > len(best_step):
                best_step = name
        if best_step:
            port = ref[len(best_step) + 1:]
            return IROutputRef(step=best_step, port=port)

        # Fallback: simple first-dot split
        step, _, port = ref.partition(".")
        return IROutputRef(step=step, port=port)

    # Bare step name — use the output name as the port
    if ref in step_names:
        return IROutputRef(step=ref, port=output_name)

    raise ValueError(
        f"final_outputs['{output_name}']: '{ref}' is not a known step name "
        f"and has no dot separator. Expected 'step.port' or a known step name. "
        f"Known steps: {sorted(step_names)}"
    )
