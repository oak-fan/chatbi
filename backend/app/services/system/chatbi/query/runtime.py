"""ChatBI 问数运行期内部状态对象。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from cogmait_shared.core.datetime_utils import now_local, serialize_datetime

from .....constants.chatbi.query import CHATBI_SSE_COMPLETED
from .....domain.system.chatbi.datasource import ChatbiDatasourceRecord
from .....domain.system.chatbi.query import ChatbiQueryRunInput, ChatbiQueryStreamEvent
from .....domain.system.llm import CompletionResponse


@dataclass
class RunMeta:
    request_id: str
    model_name: str | None = None
    total_tokens: int = 0
    rewrite_latency_ms: int | None = None
    intent_latency_ms: int | None = None
    datasource_select_latency_ms: int | None = None
    schema_select_latency_ms: int | None = None
    qsql_recall_latency_ms: int | None = None
    text2sql_latency_ms: int | None = None
    sql_candidate_latency_ms: int | None = None
    execute_latency_ms: int | None = None
    sql_validate_latency_ms: int | None = None
    summary_latency_ms: int | None = None
    sql_selected_path: str | None = None
    sql_fix_applied: bool = False
    sql_fix_attempts: int = 0
    value_founding_latency_ms: int | None = None
    is_degraded_rewrite: bool = False
    started_at: float = field(default_factory=time.perf_counter)

    def add_usage(self, response: CompletionResponse) -> None:
        if getattr(response, "model", None):
            self.model_name = str(response.model)
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        total = int(getattr(usage, "total_tokens", 0) or 0)
        if total == 0:
            total = int(getattr(usage, "prompt_tokens", 0) or 0) + int(
                getattr(usage, "completion_tokens", 0) or 0
            )
        self.total_tokens += total

    def add_usage_tokens(
        self,
        *,
        total_tokens: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> None:
        if total_tokens:
            self.total_tokens += int(total_tokens)
            return
        added = int(prompt_tokens or 0) + int(completion_tokens or 0)
        if added:
            self.total_tokens += added

    def to_completed_stream_event(self, *, session_id: int | None = None) -> ChatbiQueryStreamEvent:
        return ChatbiQueryStreamEvent(
            event=CHATBI_SSE_COMPLETED,
            request_id=self.request_id,
            session_id=session_id,
            total_tokens=self.total_tokens if self.total_tokens > 0 else None,
        )

    def to_dict(self) -> dict[str, Any]:
        total_ms = int((time.perf_counter() - self.started_at) * 1000)
        return {
            "request_id": self.request_id,
            "model_name": self.model_name,
            "total_tokens": self.total_tokens,
            "rewrite_latency_ms": self.rewrite_latency_ms,
            "intent_latency_ms": self.intent_latency_ms,
            "datasource_select_latency_ms": self.datasource_select_latency_ms,
            "schema_select_latency_ms": self.schema_select_latency_ms,
            "qsql_recall_latency_ms": self.qsql_recall_latency_ms,
            "text2sql_latency_ms": self.text2sql_latency_ms,
            "sql_candidate_latency_ms": self.sql_candidate_latency_ms,
            "execute_latency_ms": self.execute_latency_ms,
            "sql_validate_latency_ms": self.sql_validate_latency_ms,
            "summary_latency_ms": self.summary_latency_ms,
            "sql_selected_path": self.sql_selected_path,
            "sql_fix_applied": self.sql_fix_applied,
            "sql_fix_attempts": self.sql_fix_attempts,
            "value_founding_latency_ms": self.value_founding_latency_ms,
            "is_degraded_rewrite": self.is_degraded_rewrite,
            "latency_ms": total_ms,
        }


@dataclass
class RunState:
    """保存单次问数运行中会跨阶段传递的状态。"""

    user_question: str
    rewritten_question: str
    snapshot_rewritten_question: str
    pipeline_question: str
    session_id: int | None
    bound_datasource_id: int | None
    current_time: str
    datasource_id: int | None = None
    user_message_id: int | None = None
    intent_value: str | None = None
    intent_result: dict[str, Any] = field(default_factory=dict)
    intent_detail: dict[str, Any] = field(default_factory=dict)
    final_sql: str | None = None
    result_preview: dict[str, Any] | None = None
    resume_snapshot: dict[str, Any] | None = None
    clarification_question: str | None = None
    clarification_options: list[str] = field(default_factory=list)
    user_clarification_answer: str | None = None
    clarification_skipped: bool = False
    candidate_datasources: list[dict[str, Any]] = field(default_factory=list)
    value_founding_text: str | None = None
    schema_linking_result: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: ChatbiQueryRunInput) -> RunState:
        """从请求载荷创建单次问数的初始状态。"""
        return cls(
            user_question=payload.question,
            rewritten_question=payload.question,
            snapshot_rewritten_question=payload.question,
            pipeline_question=payload.question,
            session_id=payload.session_id,
            bound_datasource_id=None if payload.clarification_token else payload.datasource_id,
            current_time=serialize_datetime(now_local()) or "",
        )


@dataclass
class RunContext:
    """聚合问数运行中频繁成组传递的对象。"""

    payload: ChatbiQueryRunInput
    state: RunState
    meta: RunMeta


@dataclass
class SqlExecutionResult:
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None


@dataclass
class SchemaSelectionResult:
    text: str
    event: ChatbiQueryStreamEvent
    schema: Any | None = None
    linking_event: ChatbiQueryStreamEvent | None = None


@dataclass
class DatasourceResolution:
    record: ChatbiDatasourceRecord | None = None
    terminal_summary: str | None = None
    outcome: str | None = None
