"""Types for the independent ChatBI single-agent iterative SQL flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SingleAgentToolCall:
    """One tool call requested by the single SQL agent."""

    tool: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SingleAgentStep:
    """One LLM iteration plus the tool observations it triggered."""

    round_index: int
    thought: str
    current_sql: str | None
    confidence: float
    final_answer: bool
    tool_calls: list[SingleAgentToolCall] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    raw_output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "thought": self.thought,
            "current_sql": self.current_sql,
            "confidence": self.confidence,
            "final_answer": self.final_answer,
            "tool_calls": [
                {"tool": call.tool, "params": dict(call.params)} for call in self.tool_calls
            ],
            "tool_results": list(self.tool_results),
            "raw_output": dict(self.raw_output),
            "error": self.error,
        }


__all__ = ["SingleAgentStep", "SingleAgentToolCall"]
