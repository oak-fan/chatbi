"""Backend-neutral observability provider contracts."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Protocol

from .context import ObservabilityContext


class ObservabilityProvider(Protocol):
    """Protocol implemented by all observability providers."""

    def trace(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AbstractContextManager[ObservabilityContext]: ...

    def span(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AbstractContextManager[ObservabilityContext]: ...

    def record_llm_call(self, payload: dict[str, Any]) -> None: ...

    def record_embedding(self, payload: dict[str, Any]) -> None: ...

    def record_tool_call(self, payload: dict[str, Any]) -> None: ...

    def record_workflow_node(self, payload: dict[str, Any]) -> None: ...

    def record_agent_step(self, payload: dict[str, Any]) -> None: ...

    def record_error(
        self,
        error: Exception,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    def update_current_trace(self, metadata: dict[str, Any] | None = None) -> None: ...

    def flush(self) -> None: ...

    def shutdown(self) -> None: ...


@contextmanager
def null_observation_context(
    context: ObservabilityContext | None = None,
) -> Iterator[ObservabilityContext]:
    """Return a backend-neutral no-op observation context."""

    yield context or ObservabilityContext()
