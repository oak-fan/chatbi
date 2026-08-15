"""No-op observability provider."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any

from .base import null_observation_context
from .context import ObservabilityContext


class NoopObservabilityProvider:
    """Default provider for customer delivery and disabled observability."""

    def trace(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AbstractContextManager[ObservabilityContext]:
        del name, metadata, kwargs
        return null_observation_context()

    def span(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AbstractContextManager[ObservabilityContext]:
        del name, metadata, kwargs
        return null_observation_context()

    def record_llm_call(self, payload: dict[str, Any]) -> None:
        del payload

    def record_embedding(self, payload: dict[str, Any]) -> None:
        del payload

    def record_tool_call(self, payload: dict[str, Any]) -> None:
        del payload

    def record_workflow_node(self, payload: dict[str, Any]) -> None:
        del payload

    def record_agent_step(self, payload: dict[str, Any]) -> None:
        del payload

    def record_error(self, error: Exception, metadata: dict[str, Any] | None = None) -> None:
        del error, metadata

    def update_current_trace(self, metadata: dict[str, Any] | None = None) -> None:
        del metadata

    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None
