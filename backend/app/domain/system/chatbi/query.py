"""ChatBI 问数编排领域对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ChatbiQueryIntent(StrEnum):
    """问数意图识别结果（LLM choice / intent 字段取值）。"""

    QUERY = "query"
    CLARIFICATION = "clarification"
    UNRELATED = "unrelated"

VALID_SCHEMA_FORMATS = frozenset({"ddl", "summary", "light", "single"})
VALID_PROMPT_FORMATS = frozenset({"direct", "chain_of_thought", "problem_decomposition"})


def validate_candidate_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        path = path.strip()
        if not path or path in seen:
            continue
        parts = path.split(":", 1)
        if len(parts) != 2:
            msg = f"候选路径格式错误: '{path}'，应为 schema_format:prompt_format"
            raise ValueError(msg)
        schema_fmt, prompt_fmt = parts
        if schema_fmt not in VALID_SCHEMA_FORMATS:
            msg = f"不支持的 schema 格式: '{schema_fmt}'，可选: {', '.join(sorted(VALID_SCHEMA_FORMATS))}"
            raise ValueError(msg)
        if prompt_fmt not in VALID_PROMPT_FORMATS:
            msg = f"不支持的提示词格式: '{prompt_fmt}'，可选: {', '.join(sorted(VALID_PROMPT_FORMATS))}"
            raise ValueError(msg)
        seen.add(path)
        out.append(path)
    if not out:
        msg = "sql_candidate_paths 不能为空列表"
        raise ValueError(msg)
    return out


def _strip_required(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        msg = f"{field_name} 不能为空"
        raise ValueError(msg)
    return text

@dataclass(slots=True)
class ChatbiQueryRunOptions:
    """问数链路运行选项；默认保持完整链路。"""

    schema_selection_enabled: bool = True
    qsql_recall_enabled: bool = True
    business_knowledge_recall_enabled: bool = True
    sql_fix_enabled: bool = True
    clarification_enabled: bool = True
    intent_enabled: bool = True
    rewrite_enabled: bool = True
    summary_enabled: bool = True
    sql_candidate_paths: list[str] = field(default_factory=lambda: ["ddl:chain_of_thought"])
    sql_selection_enabled: bool = True
    sql_validate_enabled: bool = True
    schema_top_k: int | None = None
    schema_full_if_small: bool = False
    schema_small_table_threshold: int = 15
    completion_model: str | None = None
    sql_fix_max_attempts: int | None = None
    value_founding_enabled: bool = True
    value_search_enabled: bool = False
    rag_enabled: bool = False
    group_by_audit_enabled: bool = False

    def __post_init__(self) -> None:
        self.sql_candidate_paths = validate_candidate_paths(self.sql_candidate_paths)
        if self.schema_top_k is not None:
            self.schema_top_k = max(1, int(self.schema_top_k))
        if self.schema_small_table_threshold <= 0:
            self.schema_small_table_threshold = 15
        if self.sql_fix_max_attempts is not None:
            self.sql_fix_max_attempts = max(0, int(self.sql_fix_max_attempts))
        if self.completion_model is not None:
            model = self.completion_model.strip()
            self.completion_model = model or None


@dataclass(slots=True)
class ChatbiQueryRunInput:
    """问数流式请求入参。"""

    user_id: int
    question: str
    datasource_id: int | None = None
    session_id: int | None = None
    clarification_token: str | None = None
    clarification_skip: bool = False
    request_id: str | None = None
    options: ChatbiQueryRunOptions = field(default_factory=ChatbiQueryRunOptions)

    def __post_init__(self) -> None:
        self.question = _strip_required(self.question, field_name="question")
        if self.datasource_id is not None and self.datasource_id <= 0:
            raise ValueError("datasource_id 非法")
        if self.session_id is not None and self.session_id <= 0:
            raise ValueError("session_id 非法")
        if self.clarification_token is not None:
            token = self.clarification_token.strip()
            self.clarification_token = token or None


@dataclass(slots=True)
class ChatbiQueryStreamEvent:
    """问数 SSE 事件（服务层 snake_case 字段，由 API 层映射为对外 camelCase）。"""

    event: str
    request_id: str | None = None
    session_id: int | None = None
    question: str | None = None
    is_degraded: bool | None = None
    intent: str | None = None
    intent_detail: dict[str, Any] = field(default_factory=dict)
    missing_datasource: bool | None = None
    clarification_token: str | None = None
    options: list[Any] = field(default_factory=list)
    sql: str | None = None
    sql_fixed: bool | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool | None = None
    text: str | None = None
    schema_fields: list[str] = field(default_factory=list)
    schema_linking: dict[str, Any] = field(default_factory=dict)
    business_knowledge_hits: list[dict[str, Any]] = field(default_factory=list)
    qsql_hits: list[dict[str, Any]] = field(default_factory=list)
    sql_candidates: list[dict[str, Any]] = field(default_factory=list)
    sql_selection: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    total_tokens: int | None = None
    value_founding_literals: list[dict[str, Any]] = field(default_factory=list)
    value_founding_matches: list[dict[str, Any]] = field(default_factory=list)
    value_search_matches: list[dict[str, Any]] = field(default_factory=list)
    rag_knowledge_hits: list[dict[str, Any]] = field(default_factory=list)
    group_audit: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ChatbiQueryIntent",
    "ChatbiQueryRunInput",
    "ChatbiQueryRunOptions",
    "ChatbiQueryStreamEvent",
    "VALID_SCHEMA_FORMATS",
    "VALID_PROMPT_FORMATS",
    "validate_candidate_paths",
]
