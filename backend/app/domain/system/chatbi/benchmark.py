"""ChatBI 基准评价领域对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from ....constants.chatbi.query import CHATBI_PAGE_DEFAULT_SIZE, CHATBI_PAGE_MAX_SIZE
from .query import validate_candidate_paths


class BenchmarkDatasetCode(StrEnum):
    BIRD = "BIRD"
    BEAVER = "BEAVER"


class BenchmarkDatasetStatus(StrEnum):
    READY = "READY"
    PARTIAL_READY = "PARTIAL_READY"
    NOT_READY = "NOT_READY"
    DISABLED = "DISABLED"


class BenchmarkDatasourceStatus(StrEnum):
    READY = "READY"
    SCHEMA_NOT_READY = "SCHEMA_NOT_READY"
    CONNECTION_FAILED = "CONNECTION_FAILED"
    DISABLED = "DISABLED"


class BenchmarkRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class BenchmarkCaseStatus(StrEnum):
    SUCCESS = "SUCCESS"
    EXEC_ERROR = "EXEC_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    TIMEOUT = "TIMEOUT"
    SKIPPED = "SKIPPED"
    RERUNNING = "RERUNNING"


class BenchmarkMetricName(StrEnum):
    EXECUTION_ACCURACY = "execution_accuracy"
    TABLE_F1 = "table_f1"
    COLUMN_F1 = "column_f1"
    JOIN_F1 = "join_f1"
    DOMAIN_KNOWLEDGE_F1 = "domain_knowledge_f1"
    VALID_SQL_RATE = "valid_sql_rate"
    EXECUTION_ERROR_RATE = "execution_error_rate"
    TIMEOUT_RATE = "timeout_rate"
    AVG_ELAPSED_MS = "avg_elapsed_ms"
    AVG_GENERATED_SQL_EXECUTE_MS = "avg_generated_sql_execute_ms"
    AVG_GOLD_SQL_EXECUTE_MS = "avg_gold_sql_execute_ms"
    AVG_TOTAL_TOKENS = "avg_total_tokens"


class BenchmarkMethodType(StrEnum):
    LUOSHU_CHATBI = "LUOSHU_CHATBI"
    DIN_SQL = "DIN_SQL"
    MULTI_AGENT = "MULTI_AGENT"
    SINGLE_AGENT = "SINGLE_AGENT"


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _positive_id(value: int, *, field_name: str) -> int:
    if int(value) <= 0:
        msg = f"{field_name} 非法"
        raise ValueError(msg)
    return int(value)


def _validate_page(page: int, size: int) -> tuple[int, int]:
    if page < 1:
        msg = "page 非法"
        raise ValueError(msg)
    if size < 1 or size > CHATBI_PAGE_MAX_SIZE:
        msg = "size 非法"
        raise ValueError(msg)
    return page, size


@dataclass(slots=True)
class BenchmarkMethodConfig:
    """评价方法配置快照。"""

    model: str = "default"
    prompt_version: str = "default"
    schema_selection_enabled: bool = True
    qsql_recall_enabled: bool = True
    business_knowledge_recall_enabled: bool = True
    sql_fix_enabled: bool = True
    evidence_enabled: bool = False
    rewrite_enabled: bool = True
    summary_enabled: bool = True
    sql_candidate_paths: list[str] = field(default_factory=lambda: ["ddl:chain_of_thought"])
    sql_selection_enabled: bool = True
    sql_validate_enabled: bool = True
    schema_top_k: int | None = None
    schema_full_if_small: bool = False
    schema_small_table_threshold: int = 15
    sql_fix_max_attempts: int | None = None
    value_founding_enabled: bool = True
    value_search_enabled: bool = False
    rag_enabled: bool = False
    group_by_audit_enabled: bool = False

    def __post_init__(self) -> None:
        self.sql_candidate_paths = validate_candidate_paths(self.sql_candidate_paths)

    def to_snapshot(self, method_type: str) -> dict[str, Any]:
        return {
            "method_type": method_type,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "schema_selection_enabled": self.schema_selection_enabled,
            "qsql_recall_enabled": self.qsql_recall_enabled,
            "business_knowledge_recall_enabled": self.business_knowledge_recall_enabled,
            "sql_fix_enabled": self.sql_fix_enabled,
            "evidence_enabled": self.evidence_enabled,
            "rewrite_enabled": self.rewrite_enabled,
            "summary_enabled": self.summary_enabled,
            "sql_candidate_paths": self.sql_candidate_paths,
            "sql_selection_enabled": self.sql_selection_enabled,
            "sql_validate_enabled": self.sql_validate_enabled,
            "schema_top_k": self.schema_top_k,
            "schema_full_if_small": self.schema_full_if_small,
            "schema_small_table_threshold": self.schema_small_table_threshold,
            "sql_fix_max_attempts": self.sql_fix_max_attempts,
            "value_founding_enabled": self.value_founding_enabled,
            "value_search_enabled": self.value_search_enabled,
            "rag_enabled": self.rag_enabled,
            "group_by_audit_enabled": self.group_by_audit_enabled,
        }


@dataclass(slots=True)
class BenchmarkRunCreateInput:
    user_id: int
    dataset_id: int
    method_type: str = BenchmarkMethodType.LUOSHU_CHATBI.value
    method_config: BenchmarkMethodConfig = field(default_factory=BenchmarkMethodConfig)
    selected_datasource_ids: list[int] | None = None
    source_group: str | None = None
    sample_limit: int | None = None
    sample_ids: list[int] | None = None
    concurrency: int = 1
    timeout_seconds: int = 60

    def __post_init__(self) -> None:
        self.dataset_id = _positive_id(self.dataset_id, field_name="dataset_id")
        supported_methods = {item.value for item in BenchmarkMethodType}
        if self.method_type not in supported_methods:
            msg = "method_type value is not supported"
            raise ValueError(msg)
        if self.selected_datasource_ids is not None:
            ids = [
                _positive_id(item, field_name="selected_datasource_ids")
                for item in self.selected_datasource_ids
            ]
            self.selected_datasource_ids = sorted(set(ids))
        self.source_group = _strip_optional(self.source_group)
        if self.sample_limit is not None and self.sample_limit <= 0:
            msg = "sample_limit 非法"
            raise ValueError(msg)
        if self.sample_ids is not None:
            ids = [
                _positive_id(item, field_name="sample_ids")
                for item in self.sample_ids
            ]
            self.sample_ids = sorted(set(ids))
        if self.concurrency < 1 or self.concurrency > 20:
            msg = "concurrency 非法"
            raise ValueError(msg)
        if self.timeout_seconds < 1 or self.timeout_seconds > 600:
            msg = "timeout_seconds 非法"
            raise ValueError(msg)


@dataclass(slots=True)
class BenchmarkRunListParams:
    user_id: int
    page: int = 1
    size: int = CHATBI_PAGE_DEFAULT_SIZE
    dataset_id: int | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        self.page, self.size = _validate_page(self.page, self.size)
        if self.dataset_id is not None:
            self.dataset_id = _positive_id(self.dataset_id, field_name="dataset_id")
        self.status = _strip_optional(self.status)


@dataclass(slots=True)
class BenchmarkCaseListParams:
    run_id: int
    user_id: int
    page: int = 1
    size: int = CHATBI_PAGE_DEFAULT_SIZE
    status: str | None = None

    def __post_init__(self) -> None:
        self.run_id = _positive_id(self.run_id, field_name="run_id")
        self.page, self.size = _validate_page(self.page, self.size)
        self.status = _strip_optional(self.status)


@dataclass(slots=True)
class BenchmarkDatasetDatasourceUpsertInput:
    user_id: int
    dataset_id: int
    datasource_id: int
    db_id: str
    display_name: str
    status: str | None = None
    sort_order: int = 0

    def __post_init__(self) -> None:
        self.dataset_id = _positive_id(self.dataset_id, field_name="dataset_id")
        self.datasource_id = _positive_id(self.datasource_id, field_name="datasource_id")
        self.db_id = _strip_optional(self.db_id) or ""
        if not self.db_id:
            msg = "db_id 不能为空"
            raise ValueError(msg)
        self.display_name = _strip_optional(self.display_name) or self.db_id
        self.status = _strip_optional(self.status)
        statuses = {item.value for item in BenchmarkDatasourceStatus}
        if self.status is not None and self.status not in statuses:
            msg = "status 取值不支持"
            raise ValueError(msg)
        if self.sort_order < 0:
            msg = "sort_order 非法"
            raise ValueError(msg)


@dataclass(slots=True)
class BenchmarkDatasetRecord:
    id: int
    dataset_code: str
    display_name: str
    description: str | None
    current_version: str
    sample_count: int
    datasource_count: int
    status: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class BenchmarkDatasetDatasourceRecord:
    id: int
    dataset_id: int
    datasource_id: int
    db_id: str
    display_name: str
    status: str
    sample_count: int
    sort_order: int
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class BenchmarkSampleRecord:
    id: int
    sample_code: str
    dataset_id: int
    dataset_version: str
    datasource_id: int
    db_id: str
    source_group: str
    question: str
    gold_sql: str
    evidence: str | None
    ref_json: dict[str, Any]
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class BenchmarkRunRecord:
    id: int
    dataset_id: int
    dataset_code: str
    dataset_version: str
    method_type: str
    method_config_snapshot: dict[str, Any]
    selected_datasource_ids: list[int] | None
    source_group: str | None
    sample_limit: int | None
    concurrency: int
    timeout_seconds: int
    status: str
    total_count: int
    processed_count: int
    success_count: int
    failed_count: int
    last_error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_by: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class BenchmarkCaseResultRecord:
    id: int
    run_id: int
    sample_id: int
    dataset_id: int
    datasource_id: int
    sample_code: str
    question_snapshot: str
    gold_sql_snapshot: str
    generated_sql: str | None
    execution_accuracy: float | None
    table_f1: float | None
    column_f1: float | None
    join_f1: float | None
    domain_knowledge_f1: float | None
    status: str
    error_message: str | None
    trace_id: str | None
    detail_json: dict[str, Any]
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    generated_sql_execute_ms: int | None
    gold_sql_execute_ms: int | None
    started_at: datetime | None
    finished_at: datetime | None
    elapsed_ms: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class BenchmarkMetricSummaryRecord:
    id: int
    run_id: int
    metric_name: str
    metric_value: float
    sample_count: int
    extra_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


__all__ = [
    "BenchmarkCaseListParams",
    "BenchmarkCaseResultRecord",
    "BenchmarkCaseStatus",
    "BenchmarkDatasetCode",
    "BenchmarkDatasetDatasourceRecord",
    "BenchmarkDatasetRecord",
    "BenchmarkDatasetStatus",
    "BenchmarkDatasourceStatus",
    "BenchmarkMethodConfig",
    "BenchmarkMethodType",
    "BenchmarkMetricName",
    "BenchmarkMetricSummaryRecord",
    "BenchmarkRunCreateInput",
    "BenchmarkRunListParams",
    "BenchmarkRunRecord",
    "BenchmarkRunStatus",
    "BenchmarkSampleRecord",
]
