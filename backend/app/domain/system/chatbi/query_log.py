"""ChatBI 问数日志领域对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _strip_required(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        msg = f"{field_name} 不能为空"
        raise ValueError(msg)
    return text


def _validate_optional_positive_id(value: int | None, *, field_name: str) -> int | None:
    if value is not None and value <= 0:
        msg = f"{field_name} 非法"
        raise ValueError(msg)
    return value


def _validate_positive_id(value: int, *, field_name: str) -> int:
    if value <= 0:
        msg = f"{field_name} 非法"
        raise ValueError(msg)
    return value


@dataclass(slots=True)
class ChatbiQueryLogCreateInput:
    """块 4 问数编排写入 query_log 的入参。"""

    assistant_message_id: int
    user_question: str
    user_id: int
    user_message_id: int | None = None
    request_id: str | None = None
    datasource_id: int | None = None
    rewritten_question: str | None = None
    intent: str | None = None
    final_sql: str | None = None
    result_preview: dict[str, Any] | list[Any] | None = None
    latency_ms: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.assistant_message_id = _validate_positive_id(
            self.assistant_message_id,
            field_name="assistant_message_id",
        )
        self.user_id = _validate_positive_id(self.user_id, field_name="user_id")
        self.user_message_id = _validate_optional_positive_id(
            self.user_message_id,
            field_name="user_message_id",
        )
        self.datasource_id = _validate_optional_positive_id(
            self.datasource_id,
            field_name="datasource_id",
        )
        self.user_question = _strip_required(self.user_question, field_name="user_question")
        if self.latency_ms is not None and self.latency_ms < 0:
            msg = "latency_ms 非法"
            raise ValueError(msg)
        if self.meta is None:
            self.meta = {}


@dataclass(slots=True)
class ChatbiQueryLogRecord:
    """问数日志详情。"""

    id: int
    assistant_message_id: int
    user_message_id: int | None
    request_id: str | None
    datasource_id: int | None
    user_question: str
    rewritten_question: str | None
    intent: str | None
    final_sql: str | None
    result_preview: dict[str, Any] | list[Any] | None
    latency_ms: int | None
    meta: dict[str, Any]
    created_by: int | None
    created_at: datetime
    updated_at: datetime


__all__ = ["ChatbiQueryLogCreateInput", "ChatbiQueryLogRecord"]
