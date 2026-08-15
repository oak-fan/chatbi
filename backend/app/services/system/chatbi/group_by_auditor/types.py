"""Types for the GROUP BY auditor agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AuditToolCall:
    """One tool call requested by the auditor agent."""

    tool: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AuditStep:
    """One LLM iteration plus the tool observations it triggered."""

    round_index: int
    thought: str
    issues: list[dict[str, Any]]
    tool_calls: list[AuditToolCall] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    final_sql: str | None = None
    done: bool = False
    raw_output: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "thought": self.thought,
            "issues": self.issues,
            "tool_calls": [
                {"tool": call.tool, "params": dict(call.params)} for call in self.tool_calls
            ],
            "tool_results": list(self.tool_results),
            "final_sql": self.final_sql,
            "done": self.done,
            "raw_output": dict(self.raw_output),
        }


@dataclass
class AuditResult:
    """Final result of the GROUP BY audit."""

    original_sql: str
    final_sql: str
    changed: bool
    issues: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_sql": self.original_sql,
            "final_sql": self.final_sql,
            "changed": self.changed,
            "issues": self.issues,
            "steps": self.steps,
            "confidence": self.confidence,
        }


__all__ = ["AuditResult", "AuditStep", "AuditToolCall"]
