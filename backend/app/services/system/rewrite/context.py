"""问题改写输入输出结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RewriteStrategyType(StrEnum):
    """改写策略类型。"""

    LLM = "llm"
    NOOP = "noop"


@dataclass(slots=True)
class RewriteMessage:
    """对话历史单条。"""

    role: str
    content: str

    def __post_init__(self) -> None:
        self.role = _normalize_required_string(self.role, field_name="role")
        self.content = _normalize_required_string(self.content, field_name="content")


@dataclass(slots=True)
class RewriteInput:
    """改写请求输入。"""

    original_question: str
    recent_messages: list[RewriteMessage] | None = None
    glossary: dict[str, Any] | None = None
    request_id: str | None = None
    user_id: str | None = None

    def __post_init__(self) -> None:
        self.original_question = _normalize_required_string(
            self.original_question,
            field_name="original_question",
        )
        if self.recent_messages is not None:
            self.recent_messages = list(self.recent_messages)
        if self.glossary is not None:
            self.glossary = dict(self.glossary)
        self.request_id = _normalize_optional_string(self.request_id)
        self.user_id = _normalize_optional_string(self.user_id)

    @property
    def has_history(self) -> bool:
        return bool(self.recent_messages)

    @property
    def has_glossary(self) -> bool:
        return bool(self.glossary)


@dataclass(slots=True)
class RewriteOutput:
    """改写结果输出。"""

    rewritten_question: str
    original_question: str
    is_degraded: bool
    degradation_reason: str | None
    strategy_name: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.rewritten_question = _normalize_required_string(
            self.rewritten_question,
            field_name="rewritten_question",
        )
        self.original_question = _normalize_required_string(
            self.original_question,
            field_name="original_question",
        )
        self.strategy_name = _normalize_required_string(
            self.strategy_name,
            field_name="strategy_name",
        )
        if self.is_degraded:
            if self.degradation_reason is None or not str(self.degradation_reason).strip():
                raise ValueError("is_degraded 为 true 时 degradation_reason 不能为空")
            self.degradation_reason = str(self.degradation_reason).strip()
        else:
            self.degradation_reason = None
        self.metadata = dict(self.metadata)


def _normalize_required_string(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} 不能为空")
    return normalized


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


__all__ = [
    "RewriteInput",
    "RewriteMessage",
    "RewriteOutput",
    "RewriteStrategyType",
]
