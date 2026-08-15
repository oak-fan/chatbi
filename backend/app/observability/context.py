"""Observability context objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class ObservabilityContext:
    """Backend-neutral trace/span context."""

    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ObservationPayload:
    """Sanitized payload passed to observability providers."""

    name: str
    metadata: dict[str, Any] = field(default_factory=dict)
