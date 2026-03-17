"""Runtime value store — holds all addressed values during execution."""
from __future__ import annotations

from typing import Any

from graphsmith.exceptions import ExecutionError


_MISSING = object()


class ValueStore:
    """Flat address → value map populated during graph execution."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def put(self, address: str, value: Any) -> None:
        """Store *value* at *address*. Overwrites are forbidden."""
        if address in self._data:
            raise ExecutionError(
                f"Address '{address}' already has a value — double write detected"
            )
        self._data[address] = value

    def get(self, address: str) -> Any:
        """Retrieve the value at *address*.

        Raises ExecutionError if the address has not been written.
        """
        val = self._data.get(address, _MISSING)
        if val is _MISSING:
            raise ExecutionError(
                f"Address '{address}' has no value. "
                f"Available: {sorted(self._data)}"
            )
        return val

    def has(self, address: str) -> bool:
        return address in self._data

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow copy of all stored values."""
        return dict(self._data)
