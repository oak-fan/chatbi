"""Observability provider names."""

from __future__ import annotations

from enum import StrEnum


class ObservabilityProviderName(StrEnum):
    NOOP = "noop"
    LANGFUSE = "langfuse"


__all__ = ["ObservabilityProviderName"]
