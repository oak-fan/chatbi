"""ChatBI 业务知识领域对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from ....constants.chatbi.query import CHATBI_PAGE_DEFAULT_SIZE, CHATBI_PAGE_MAX_SIZE


class ChatbiBusinessKnowledgeScope(StrEnum):
    GLOBAL = "GLOBAL"
    SYSTEM_INFERRED = "SYSTEM_INFERRED"


class ChatbiBusinessKnowledgeKind(StrEnum):
    DIMENSION = "DIMENSION"
    METRIC = "METRIC"
    TIME = "TIME"
    TERM = "TERM"


_BIZKN_UPDATE_FIELDS = frozenset({"content", "scope", "kind", "datasource_id"})


def _strip_required(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        msg = f"{field_name} 不能为空"
        raise ValueError(msg)
    return text


def _validate_datasource_id(datasource_id: int) -> int:
    if datasource_id <= 0:
        msg = "datasource_id 非法"
        raise ValueError(msg)
    return datasource_id


def _validate_record_id(record_id: int) -> int:
    if record_id <= 0:
        msg = "record_id 非法"
        raise ValueError(msg)
    return record_id


def _validate_scope(scope: str) -> str:
    return _strip_required(scope, field_name="scope")


def _validate_kind(kind: str) -> str:
    return _strip_required(kind, field_name="kind")


@dataclass(slots=True)
class ChatbiBusinessKnowledgeCreateInput:
    user_id: int
    content: str
    scope: str
    kind: str
    datasource_id: int

    def __post_init__(self) -> None:
        self.content = _strip_required(self.content, field_name="content")
        self.scope = _validate_scope(self.scope)
        self.kind = _validate_kind(self.kind)
        self.datasource_id = _validate_datasource_id(self.datasource_id)


@dataclass(slots=True)
class ChatbiBusinessKnowledgeUpdateInput:
    user_id: int
    record_id: int
    content: str | None = None
    scope: str | None = None
    kind: str | None = None
    datasource_id: int | None = None
    provided_fields: frozenset[str] | set[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.record_id <= 0:
            msg = "record_id 非法"
            raise ValueError(msg)
        self.provided_fields = frozenset(str(item) for item in self.provided_fields)
        if not self.provided_fields:
            self.provided_fields = frozenset(
                field_name
                for field_name in _BIZKN_UPDATE_FIELDS
                if getattr(self, field_name) is not None
            )
        if not self.provided_fields:
            msg = "至少提供一个更新字段"
            raise ValueError(msg)
        unknown_fields = self.provided_fields - _BIZKN_UPDATE_FIELDS
        if unknown_fields:
            msg = "更新字段非法"
            raise ValueError(msg)
        for field_name in self.provided_fields:
            if getattr(self, field_name) is None:
                msg = f"{field_name} 不能为 null"
                raise ValueError(msg)
        if self.content is not None:
            self.content = _strip_required(self.content, field_name="content")
        if self.scope is not None:
            self.scope = _validate_scope(self.scope)
        if self.kind is not None:
            self.kind = _validate_kind(self.kind)
        if self.datasource_id is not None:
            self.datasource_id = _validate_datasource_id(self.datasource_id)


@dataclass(slots=True)
class ChatbiBusinessKnowledgeListParams:
    user_id: int
    page: int = 1
    size: int = CHATBI_PAGE_DEFAULT_SIZE
    scope: str | None = None
    kind: str | None = None
    datasource_id: int | None = None

    def __post_init__(self) -> None:
        if self.page < 1:
            msg = "page 非法"
            raise ValueError(msg)
        if self.size < 1 or self.size > CHATBI_PAGE_MAX_SIZE:
            msg = "size 非法"
            raise ValueError(msg)
        if self.scope is not None:
            self.scope = self.scope.strip() or None
            if self.scope is not None:
                self.scope = _validate_scope(self.scope)
        if self.kind is not None:
            self.kind = self.kind.strip() or None
            if self.kind is not None:
                self.kind = _validate_kind(self.kind)
        if self.datasource_id is not None:
            self.datasource_id = _validate_datasource_id(self.datasource_id)


@dataclass(slots=True)
class ChatbiBusinessKnowledgeDeleteInput:
    user_id: int
    record_id: int

    def __post_init__(self) -> None:
        self.record_id = _validate_record_id(self.record_id)


@dataclass(slots=True)
class ChatbiBusinessKnowledgeRecord:
    """业务知识详情。"""

    id: int
    content: str
    scope: str
    kind: str
    datasource_id: int
    created_at: datetime
    updated_at: datetime


__all__ = [
    "ChatbiBusinessKnowledgeCreateInput",
    "ChatbiBusinessKnowledgeDeleteInput",
    "ChatbiBusinessKnowledgeKind",
    "ChatbiBusinessKnowledgeListParams",
    "ChatbiBusinessKnowledgeRecord",
    "ChatbiBusinessKnowledgeScope",
    "ChatbiBusinessKnowledgeUpdateInput",
]
