"""通用向量能力领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VectorBackendType(str, Enum):
    """向量后端类型。"""

    POSTGRES = "postgres"
    MILVUS = "milvus"


def _normalize_positive_int(value: int, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} 必须是正整数")
    return value


def _normalize_float(value: float | int, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} 必须是数字")
    return float(value)


def _normalize_embedding(value: list[float]) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ValueError("embedding 不能为空")
    return [_normalize_float(item, field_name="embedding") for item in value]


def _normalize_file_ids(value: list[int] | None) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("file_ids 必须是数组")
    normalized_ids: list[int] = []
    seen: set[int] = set()
    for item in value:
        normalized = _normalize_positive_int(item, field_name="file_id")
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_ids.append(normalized)
    return normalized_ids


def _normalize_result_file_ids(value: list[int] | None) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("result_file_ids 必须是数组")
    normalized_ids: list[int] = []
    seen: set[int] = set()
    for item in value:
        normalized = _normalize_positive_int(item, field_name="result_file_id")
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_ids.append(normalized)
    return normalized_ids


@dataclass(slots=True)
class VectorChunkInput:
    """统一向量写入输入。"""

    knowledge_id: int
    file_id: int
    chunk_id: int
    result_file_id: int
    embedding: list[float]

    def __post_init__(self) -> None:
        self.knowledge_id = _normalize_positive_int(
            self.knowledge_id,
            field_name="knowledge_id",
        )
        self.file_id = _normalize_positive_int(self.file_id, field_name="file_id")
        self.chunk_id = _normalize_positive_int(self.chunk_id, field_name="chunk_id")
        self.result_file_id = _normalize_positive_int(
            self.result_file_id,
            field_name="result_file_id",
        )
        self.embedding = _normalize_embedding(self.embedding)


@dataclass(slots=True)
class VectorSearchInput:
    """统一向量检索输入。"""

    knowledge_id: int
    embedding: list[float]
    top_k: int
    score_threshold: float | None = None
    file_ids: list[int] | None = None
    result_file_ids: list[int] | None = None

    def __post_init__(self) -> None:
        self.knowledge_id = _normalize_positive_int(
            self.knowledge_id,
            field_name="knowledge_id",
        )
        self.embedding = _normalize_embedding(self.embedding)
        self.top_k = _normalize_positive_int(self.top_k, field_name="top_k")
        if self.score_threshold is not None:
            self.score_threshold = _normalize_float(
                self.score_threshold,
                field_name="score_threshold",
            )
        self.file_ids = _normalize_file_ids(self.file_ids)
        self.result_file_ids = _normalize_result_file_ids(self.result_file_ids)


@dataclass(slots=True)
class VectorSearchHit:
    """统一向量检索命中项。"""

    chunk_id: int
    file_id: int
    score: float


@dataclass(slots=True)
class VectorHealthRecord:
    """向量后端健康检查结果。"""

    backend: VectorBackendType
    is_healthy: bool
    detail: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "VectorBackendType",
    "VectorChunkInput",
    "VectorHealthRecord",
    "VectorSearchHit",
    "VectorSearchInput",
]
