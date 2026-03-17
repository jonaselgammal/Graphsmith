"""Project-specific exceptions."""


class GraphsmithError(Exception):
    """Base project exception."""


class ParseError(GraphsmithError):
    """Raised when a skill package cannot be parsed."""


class ValidationError(GraphsmithError):
    """Raised when a skill package is invalid."""


class ExecutionError(GraphsmithError):
    """Raised when a graph execution fails at runtime."""


class OpError(ExecutionError):
    """Raised when a primitive op fails."""


class RegistryError(GraphsmithError):
    """Raised on registry operations (publish, fetch, search)."""


class PlannerError(GraphsmithError):
    """Raised when the planner fails to produce a valid plan."""


class ProviderError(GraphsmithError):
    """Raised when an LLM provider call fails with an actionable error."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        status_code: int | None = None,
        hint: str = "",
    ) -> None:
        self.provider = provider
        self.status_code = status_code
        self.hint = hint
        full = message
        if hint:
            full = f"{message}\n  Hint: {hint}"
        super().__init__(full)
