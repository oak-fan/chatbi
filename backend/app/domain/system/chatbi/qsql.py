"""ChatBI Q-SQL 领域对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ....constants.chatbi.query import CHATBI_PAGE_DEFAULT_SIZE, CHATBI_PAGE_MAX_SIZE

_QSQL_UPDATE_FIELDS = frozenset({"question", "sql_body"})
QSQL_SCOPE_DATASOURCE = "DATASOURCE"
QSQL_SCOPE_GLOBAL = "GLOBAL"
QSQL_GLOBAL_DATASOURCE_ID = 0


def _validate_positive_id(value: int, *, field_name: str) -> int:
    if value <= 0:
        msg = f"{field_name} 非法"
        raise ValueError(msg)
    return value


def _strip_required(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        msg = f"{field_name} 不能为空"
        raise ValueError(msg)
    return text


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _normalize_scope(value: str) -> str:
    scope = value.strip().upper()
    if scope not in {QSQL_SCOPE_DATASOURCE, QSQL_SCOPE_GLOBAL}:
        msg = "scope 非法"
        raise ValueError(msg)
    return scope


@dataclass(slots=True)
class ChatbiQsqlCreateInput:
    user_id: int
    datasource_id: int
    question: str
    sql_body: str
    scope: str = QSQL_SCOPE_DATASOURCE
    source_dataset: str | None = None
    source_db_id: str | None = None
    source_sample_id: str | None = None
    sql_skeleton: str | None = None

    def __post_init__(self) -> None:
        self.scope = _normalize_scope(self.scope)
        if self.scope == QSQL_SCOPE_GLOBAL:
            if self.datasource_id != QSQL_GLOBAL_DATASOURCE_ID:
                msg = "全局 Q-SQL datasource_id 必须为 0"
                raise ValueError(msg)
        else:
            self.datasource_id = _validate_positive_id(
                self.datasource_id,
                field_name="datasource_id",
            )
        self.question = _strip_required(self.question, field_name="question")
        self.sql_body = _strip_required(self.sql_body, field_name="sql_body")
        self.source_dataset = _strip_optional(self.source_dataset)
        self.source_db_id = _strip_optional(self.source_db_id)
        self.source_sample_id = _strip_optional(self.source_sample_id)
        self.sql_skeleton = _strip_optional(self.sql_skeleton)
        if self.scope == QSQL_SCOPE_GLOBAL and self.source_dataset is None:
            msg = "全局 Q-SQL source_dataset 不能为空"
            raise ValueError(msg)


@dataclass(slots=True)
class ChatbiQsqlUpdateInput:
    user_id: int
    record_id: int
    question: str | None = None
    sql_body: str | None = None
    provided_fields: frozenset[str] | set[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        self.record_id = _validate_positive_id(self.record_id, field_name="record_id")
        self.provided_fields = frozenset(str(item) for item in self.provided_fields)
        if not self.provided_fields:
            self.provided_fields = frozenset(
                field_name
                for field_name in _QSQL_UPDATE_FIELDS
                if getattr(self, field_name) is not None
            )
        if not self.provided_fields:
            msg = "至少提供一个更新字段"
            raise ValueError(msg)
        unknown_fields = self.provided_fields - _QSQL_UPDATE_FIELDS
        if unknown_fields:
            msg = "更新字段非法"
            raise ValueError(msg)
        for field_name in self.provided_fields:
            if getattr(self, field_name) is None:
                msg = f"{field_name} 不能为 null"
                raise ValueError(msg)
        if self.question is not None:
            self.question = _strip_required(self.question, field_name="question")
        if self.sql_body is not None:
            self.sql_body = _strip_required(self.sql_body, field_name="sql_body")


@dataclass(slots=True)
class ChatbiQsqlListParams:
    user_id: int
    page: int = 1
    size: int = CHATBI_PAGE_DEFAULT_SIZE
    datasource_id: int | None = None

    def __post_init__(self) -> None:
        if self.page < 1:
            msg = "page 非法"
            raise ValueError(msg)
        if self.size < 1 or self.size > CHATBI_PAGE_MAX_SIZE:
            msg = "size 非法"
            raise ValueError(msg)
        if self.datasource_id is not None:
            self.datasource_id = _validate_positive_id(
                self.datasource_id,
                field_name="datasource_id",
            )


@dataclass(slots=True)
class ChatbiQsqlDeleteInput:
    user_id: int
    record_id: int

    def __post_init__(self) -> None:
        self.record_id = _validate_positive_id(self.record_id, field_name="record_id")


@dataclass(slots=True)
class ChatbiQsqlRecord:
    """Q-SQL 详情。"""

    id: int
    datasource_id: int
    question: str
    sql_body: str
    llm_simplified_description: str | None
    scope: str
    source_dataset: str | None
    source_db_id: str | None
    source_sample_id: str | None
    sql_skeleton: str | None
    created_at: datetime
    updated_at: datetime


__all__ = [
    "ChatbiQsqlCreateInput",
    "ChatbiQsqlDeleteInput",
    "ChatbiQsqlListParams",
    "ChatbiQsqlRecord",
    "ChatbiQsqlUpdateInput",
    "QSQL_GLOBAL_DATASOURCE_ID",
    "QSQL_SCOPE_DATASOURCE",
    "QSQL_SCOPE_GLOBAL",
]
