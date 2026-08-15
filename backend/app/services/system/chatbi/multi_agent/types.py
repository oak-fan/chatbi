"""Types for the independent ChatBI multi-agent SQL flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentCallResult:
    name: str
    output: dict[str, Any]
    raw_content: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, int | None] = field(default_factory=dict)


@dataclass(slots=True)
class SqlProbeResult:
    mode: str
    sql: str
    success: bool
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    error: str | None = None


@dataclass(slots=True)
class KnowledgeSearchHit:
    db_name: str
    table_name: str
    content: str
    score: float
    source_path: str
    chunk_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MultiAgentRunResult:
    sql: str
    candidates: list[dict[str, Any]]
    agent_outputs: dict[str, Any]
    tool_results: dict[str, Any]
    token_usage: dict[str, int | None]
    raw_output: dict[str, Any]
    query_stream_events: list[dict[str, Any]]


__all__ = [
    "AgentCallResult",
    "KnowledgeSearchHit",
    "MultiAgentRunResult",
    "SqlProbeResult",
]
