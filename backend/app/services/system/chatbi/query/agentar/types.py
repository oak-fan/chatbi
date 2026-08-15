"""Runtime data objects for Agentar-style SQL scaling."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AgentarSchemaView:
    """One prompt-visible schema rendering path."""

    name: str
    text: str


@dataclass(slots=True)
class SqlCandidate:
    """One generated SQL candidate and its validation/selection metadata."""

    path_name: str
    schema_format: str
    prompt_style: str
    sql: str | None = None
    original_sql: str | None = None
    fixed: bool = False
    generation_error: str | None = None
    execute_error: str | None = None
    fix_error: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int | None = None
    truncated: bool = False
    result_signature: str | None = None
    group_id: str | None = None
    group_size: int = 1
    score: float = 0.0
    wins: float = 0.0
    comparisons: int = 0
    selected: bool = False
    selection_reason: str | None = None

    @property
    def is_executable(self) -> bool:
        return bool(self.sql) and self.execute_error is None

    def to_stream_dict(self) -> dict[str, Any]:
        return {
            "path_name": self.path_name,
            "schema_format": self.schema_format,
            "prompt_style": self.prompt_style,
            "sql": self.sql,
            "original_sql": self.original_sql,
            "fixed": self.fixed,
            "generation_error": self.generation_error,
            "execute_error": self.execute_error,
            "fix_error": self.fix_error,
            "columns": list(self.columns),
            "rows": list(self.rows[:5]),
            "row_count": self.row_count,
            "truncated": self.truncated,
            "result_signature": self.result_signature,
            "group_id": self.group_id,
            "group_size": self.group_size,
            "score": self.score,
            "wins": self.wins,
            "comparisons": self.comparisons,
            "selected": self.selected,
            "selection_reason": self.selection_reason,
        }


@dataclass(slots=True)
class SqlCandidateGroup:
    """Candidates with identical execution result."""

    group_id: str
    candidates: list[SqlCandidate]
    result_signature: str
    wins: float = 0.0
    comparisons: int = 0
    selector_notes: list[str] = field(default_factory=list)

    @property
    def representative(self) -> SqlCandidate:
        return self.candidates[0]
