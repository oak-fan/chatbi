"""ChatBI 向量检索领域对象。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChatbiVectorEntity(StrEnum):
    """ChatBI 向量索引实体类型。"""

    SCHEMA = "schema"
    QSQL = "qsql"
    BUSINESS_KNOWLEDGE = "business_knowledge"


def _normalize_positive_int(value: int, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} 必须是正整数")
    return value


def _normalize_non_empty_str(value: str, *, field_name: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} 不能为空")
    return text


def _normalize_embedding(value: list[float]) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ValueError("embedding 不能为空")
    return [float(item) for item in value]


def _normalize_score(value: float | int) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("score 必须是数字")
    return float(value)


@dataclass(slots=True)
class ChatbiSchemaVectorRow:
    """schema 列向量写入行。"""

    datasource_id: int
    table_name: str
    column_name: str
    embedding: list[float]

    def __post_init__(self) -> None:
        self.datasource_id = _normalize_positive_int(
            self.datasource_id,
            field_name="datasource_id",
        )
        self.table_name = _normalize_non_empty_str(self.table_name, field_name="table_name")
        self.column_name = _normalize_non_empty_str(self.column_name, field_name="column_name")
        self.embedding = _normalize_embedding(self.embedding)


@dataclass(slots=True)
class ChatbiSchemaSearchHit:
    """schema 列向量检索命中。"""

    table_name: str
    column_name: str
    score: float

    def __post_init__(self) -> None:
        self.table_name = _normalize_non_empty_str(self.table_name, field_name="table_name")
        self.column_name = _normalize_non_empty_str(self.column_name, field_name="column_name")
        self.score = _normalize_score(self.score)


@dataclass(slots=True)
class ChatbiQsqlSearchHit:
    """Q-SQL 向量检索命中。"""

    qsql_id: int
    score: float

    def __post_init__(self) -> None:
        self.qsql_id = _normalize_positive_int(self.qsql_id, field_name="qsql_id")
        self.score = _normalize_score(self.score)


@dataclass(slots=True)
class ChatbiBusinessKnowledgeSearchHit:
    """业务知识向量检索命中。"""

    business_knowledge_id: int
    score: float

    def __post_init__(self) -> None:
        self.business_knowledge_id = _normalize_positive_int(
            self.business_knowledge_id,
            field_name="business_knowledge_id",
        )
        self.score = _normalize_score(self.score)


__all__ = [
    "ChatbiBusinessKnowledgeSearchHit",
    "ChatbiQsqlSearchHit",
    "ChatbiSchemaSearchHit",
    "ChatbiSchemaVectorRow",
    "ChatbiVectorEntity",
]
