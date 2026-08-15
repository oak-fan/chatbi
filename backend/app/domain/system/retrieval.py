from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from cogmait_shared.core.naming import camel_to_snake


class RetrievalStrategyType(StrEnum):
    SEMANTIC = "SEMANTIC"
    FULL_TEXT = "FULL_TEXT"
    KEYWORD = "KEYWORD"
    HYBRID_RRF = "HYBRID_RRF"
    HYBRID_WEIGHTED = "HYBRID_WEIGHTED"
    HYBRID_RERANK_WEIGHTED = "HYBRID_RERANK_WEIGHTED"
    SEMANTIC_THEN_RERANK = "SEMANTIC_THEN_RERANK"
    TOC_ENHANCED = "TOC_ENHANCED"
    KG_RETRIEVAL = "KG_RETRIEVAL"


class RetrievalCandidateSource(StrEnum):
    VECTOR = "vector"
    FULL_TEXT = "full_text"
    KEYWORD = "keyword"
    RERANK = "rerank"
    HYBRID = "hybrid"


class RetrievalRerankMode(StrEnum):
    POST = "post"
    WEIGHTED = "weighted"
    DISABLED = "disabled"


DEFAULT_RETRIEVAL_STRATEGY = "HYBRID_RRF"
DEFAULT_CANDIDATE_MULTIPLIER = 5
DEFAULT_RRF_K = 60
DEFAULT_KEYWORD_WEIGHT = 0.3
DEFAULT_VECTOR_WEIGHT = 0.7
DEFAULT_RERANK_ENABLED = True
DEFAULT_RERANK_MODE = RetrievalRerankMode.POST.value
SUPPORTED_RETRIEVAL_STRATEGIES: frozenset[str] = frozenset(
    {
        RetrievalStrategyType.SEMANTIC.value,
        RetrievalStrategyType.FULL_TEXT.value,
        RetrievalStrategyType.KEYWORD.value,
        RetrievalStrategyType.HYBRID_RRF.value,
        RetrievalStrategyType.HYBRID_WEIGHTED.value,
        RetrievalStrategyType.HYBRID_RERANK_WEIGHTED.value,
        RetrievalStrategyType.SEMANTIC_THEN_RERANK.value,
    }
)
SUPPORTED_RERANK_MODES: frozenset[str] = frozenset(item.value for item in RetrievalRerankMode)
RETRIEVAL_CONFIG_STORAGE_KEY_ALIASES: dict[str, str] = {
    "retrieval_strategy": "strategy",
}


def _normalize_strategy(value: str | RetrievalStrategyType | None) -> str:
    if value is None:
        return DEFAULT_RETRIEVAL_STRATEGY
    normalized = str(value).strip().upper()
    if not normalized:
        return DEFAULT_RETRIEVAL_STRATEGY
    try:
        strategy = RetrievalStrategyType(normalized).value
    except ValueError as exc:
        raise ValueError(f"retrieval_strategy 不支持: {normalized}") from exc
    if strategy not in SUPPORTED_RETRIEVAL_STRATEGIES:
        raise ValueError(f"retrieval_strategy 当前版本暂不支持: {strategy}")
    return strategy


def _normalize_int(
    value: int | None,
    *,
    field_name: str,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} 必须为整数")
    if value < min_value or value > max_value:
        raise ValueError(f"{field_name} 必须在 {min_value} 到 {max_value} 之间")
    return value


def _normalize_weight(value: float | int | None, *, field_name: str, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} 必须为数字")
    normalized = float(value)
    if normalized < 0:
        raise ValueError(f"{field_name} 不能小于 0")
    return normalized


def _normalize_bool(value: bool | None, *, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} 必须为布尔值")
    return value


def _normalize_rerank_mode(value: str | None) -> str:
    if value is None:
        return DEFAULT_RERANK_MODE
    normalized = str(value).strip() or DEFAULT_RERANK_MODE
    if normalized not in SUPPORTED_RERANK_MODES:
        raise ValueError("rerank_mode 仅支持 post、weighted 或 disabled")
    return normalized


def _normalize_storage_key(key: Any) -> Any:
    if not isinstance(key, str):
        return key
    snake_key = camel_to_snake(key)
    return RETRIEVAL_CONFIG_STORAGE_KEY_ALIASES.get(snake_key, snake_key)


@dataclass(slots=True)
class RetrievalConfig:
    strategy: str = DEFAULT_RETRIEVAL_STRATEGY
    candidate_multiplier: int = DEFAULT_CANDIDATE_MULTIPLIER
    rrf_k: int = DEFAULT_RRF_K
    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT
    vector_weight: float = DEFAULT_VECTOR_WEIGHT
    rerank_enabled: bool = DEFAULT_RERANK_ENABLED
    rerank_mode: str = DEFAULT_RERANK_MODE

    def __post_init__(self) -> None:
        self.strategy = _normalize_strategy(self.strategy)
        self.candidate_multiplier = _normalize_int(
            self.candidate_multiplier,
            field_name="candidate_multiplier",
            default=DEFAULT_CANDIDATE_MULTIPLIER,
            min_value=1,
            max_value=20,
        )
        self.rrf_k = _normalize_int(
            self.rrf_k,
            field_name="rrf_k",
            default=DEFAULT_RRF_K,
            min_value=1,
            max_value=1000,
        )
        self.keyword_weight = _normalize_weight(
            self.keyword_weight,
            field_name="keyword_weight",
            default=DEFAULT_KEYWORD_WEIGHT,
        )
        self.vector_weight = _normalize_weight(
            self.vector_weight,
            field_name="vector_weight",
            default=DEFAULT_VECTOR_WEIGHT,
        )
        if self.keyword_weight == 0 and self.vector_weight == 0:
            raise ValueError("keyword_weight 和 vector_weight 不能同时为 0")
        self.rerank_enabled = _normalize_bool(
            self.rerank_enabled,
            field_name="rerank_enabled",
            default=DEFAULT_RERANK_ENABLED,
        )
        self.rerank_mode = _normalize_rerank_mode(self.rerank_mode)

    @classmethod
    def from_sources(
        cls,
        *sources: dict[str, Any] | None,
        strategy: str | None = None,
    ) -> RetrievalConfig:
        merged: dict[str, Any] = {}
        for source in sources:
            if not source:
                continue
            merged.update({key: value for key, value in source.items() if value is not None})
        if strategy is not None:
            merged["strategy"] = strategy
        return cls(
            strategy=merged.get(
                "strategy",
                merged.get(
                    "retrieval_strategy",
                    merged.get("retrievalStrategy", DEFAULT_RETRIEVAL_STRATEGY),
                ),
            ),
            candidate_multiplier=merged.get(
                "candidate_multiplier",
                merged.get("candidateMultiplier", DEFAULT_CANDIDATE_MULTIPLIER),
            ),
            rrf_k=merged.get("rrf_k", merged.get("rrfK", DEFAULT_RRF_K)),
            keyword_weight=merged.get(
                "keyword_weight",
                merged.get("keywordWeight", DEFAULT_KEYWORD_WEIGHT),
            ),
            vector_weight=merged.get(
                "vector_weight",
                merged.get("vectorWeight", DEFAULT_VECTOR_WEIGHT),
            ),
            rerank_enabled=merged.get(
                "rerank_enabled",
                merged.get("rerankEnabled", DEFAULT_RERANK_ENABLED),
            ),
            rerank_mode=merged.get("rerank_mode", merged.get("rerankMode", DEFAULT_RERANK_MODE)),
        )

    def model_dump(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "candidate_multiplier": self.candidate_multiplier,
            "rrf_k": self.rrf_k,
            "keyword_weight": self.keyword_weight,
            "vector_weight": self.vector_weight,
            "rerank_enabled": self.rerank_enabled,
            "rerank_mode": self.rerank_mode,
        }


def normalize_retrieval_config_payload(
    payload: dict[str, Any] | None,
    *,
    strategy: str | None = None,
) -> dict[str, Any]:
    raw_config = {
        _normalize_storage_key(key): value
        for key, value in dict(payload or {}).items()
        if value is not None
    }
    config = RetrievalConfig.from_sources(raw_config, strategy=strategy)
    normalized_values = config.model_dump()
    normalized_config = dict(raw_config)
    for key in raw_config:
        if key in normalized_values:
            normalized_config[key] = normalized_values[key]
    return normalized_config


@dataclass(frozen=True, slots=True)
class RetrievalPlan:
    knowledge_id: int
    embedding_model: str | None
    tokenizer: str
    is_full_text_enabled: bool
    allowed_file_ids: tuple[int, ...]
    allowed_result_file_ids: tuple[int, ...]


@dataclass(slots=True)
class RetrievalCandidate:
    chunk_id: int
    knowledge_id: int
    file_id: int
    score: float
    rank: int
    source: str
    score_parts: dict[str, float] = field(default_factory=dict)
    rank_parts: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalHit:
    chunk_id: int
    knowledge_id: int
    file_id: int
    score: float
    source: str
    score_parts: dict[str, float] = field(default_factory=dict)
    rank_parts: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalInput:
    query: str
    embeddings_by_model: dict[str | None, list[float]]
    plans: list[RetrievalPlan]
    top_k: int
    score_threshold: float | None
    config: RetrievalConfig
    metadata: dict[str, Any] = field(default_factory=dict)
