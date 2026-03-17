"""skill.invoke op — recursive sub-skill execution."""
from __future__ import annotations

from typing import Any

from graphsmith.exceptions import ExecutionError, OpError

# Default maximum nesting depth for skill.invoke chains.
MAX_INVOKE_DEPTH = 10


def skill_invoke(
    config: dict[str, Any],
    inputs: dict[str, Any],
    *,
    registry: Any,  # LocalRegistry — typed as Any to avoid circular import
    llm_provider: Any,
    depth: int,
    call_stack: list[tuple[str, str]],
) -> dict[str, Any]:
    """Execute a sub-skill from the registry.

    Config (required):
        skill_id (str): The registry skill ID to invoke.
        version (str): The exact version to invoke.

    Inputs:
        Arbitrary — forwarded as the sub-skill's graph inputs.

    Returns:
        The sub-skill's graph outputs as this node's output ports.
    """
    # late import to avoid circular dependency
    from graphsmith.runtime.executor import run_skill_package
    from graphsmith.validator import validate_skill_package

    skill_id = config.get("skill_id")
    if not skill_id:
        raise OpError("skill.invoke requires config.skill_id")

    version = config.get("version")
    if not version:
        raise OpError("skill.invoke requires config.version")

    # Depth check
    if depth >= MAX_INVOKE_DEPTH:
        raise ExecutionError(
            f"skill.invoke depth limit ({MAX_INVOKE_DEPTH}) exceeded. "
            f"Call stack: {' → '.join(f'{s}@{v}' for s, v in call_stack)}"
        )

    # Self-recursion check
    key = (skill_id, version)
    if key in call_stack:
        raise ExecutionError(
            f"Self-recursion detected: '{skill_id}@{version}' already on call stack. "
            f"Stack: {' → '.join(f'{s}@{v}' for s, v in call_stack)}"
        )

    # Fetch and validate
    if registry is None:
        raise OpError(
            "skill.invoke requires a registry. Pass a LocalRegistry to the executor."
        )
    sub_pkg = registry.fetch(skill_id, version)
    validate_skill_package(sub_pkg)

    # Execute recursively
    result = run_skill_package(
        sub_pkg,
        inputs,
        llm_provider=llm_provider,
        registry=registry,
        _depth=depth + 1,
        _call_stack=[*call_stack, key],
    )

    return result.outputs, result.trace
