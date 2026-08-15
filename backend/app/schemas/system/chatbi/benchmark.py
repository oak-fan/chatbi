"""ChatBI 基准评价接口 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from cogmait_shared.api import SnowflakeID
from cogmait_shared.core.datetime_utils import serialize_datetime
from cogmait_shared.core.naming import snake_to_camel_dict

from ....constants.chatbi.query import CHATBI_PAGE_DEFAULT_SIZE


class _BenchmarkSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True, extra="forbid")


class _BenchmarkRequestSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=False, from_attributes=True, extra="forbid")


def _serialize_required_datetime(value: datetime) -> str:
    serialized = serialize_datetime(value)
    if serialized is None:
        raise ValueError("datetime serialization failed")
    return cast(str, serialized)


class BenchmarkMethodConfigRequest(_BenchmarkRequestSchema):
    model: str = "default"
    prompt_version: str = Field(default="default", alias="promptVersion")
    schema_selection_enabled: bool = Field(default=True, alias="schemaSelectionEnabled")
    qsql_recall_enabled: bool = Field(default=True, alias="qsqlRecallEnabled")
    business_knowledge_recall_enabled: bool = Field(
        default=True,
        alias="businessKnowledgeRecallEnabled",
    )
    sql_fix_enabled: bool = Field(default=True, alias="sqlFixEnabled")
    evidence_enabled: bool = Field(default=False, alias="evidenceEnabled")
    rewrite_enabled: bool = Field(default=True, alias="rewriteEnabled")
    summary_enabled: bool = Field(default=True, alias="summaryEnabled")
    sql_candidate_paths: list[str] = Field(default=["ddl:chain_of_thought"], alias="sqlCandidatePaths")
    sql_selection_enabled: bool = Field(default=True, alias="sqlSelectionEnabled")
    sql_validate_enabled: bool = Field(default=True, alias="sqlValidateEnabled")
    schema_top_k: int | None = Field(default=None, alias="schemaTopK")
    schema_full_if_small: bool = Field(default=False, alias="schemaFullIfSmall")
    schema_small_table_threshold: int = Field(default=15, alias="schemaSmallTableThreshold")
    sql_fix_max_attempts: int | None = Field(default=None, alias="sqlFixMaxAttempts")
    value_founding_enabled: bool = Field(default=True, alias="valueFoundingEnabled")
    value_search_enabled: bool = Field(default=False, alias="valueSearchEnabled")
    rag_enabled: bool = Field(default=False, alias="ragEnabled")
    group_by_audit_enabled: bool = Field(default=False, alias="groupByAuditEnabled")


class BenchmarkRunCreateRequest(_BenchmarkRequestSchema):
    dataset_id: SnowflakeID = Field(alias="datasetId")
    method_type: str = Field(default="LUOSHU_CHATBI", alias="methodType")
    method_config: BenchmarkMethodConfigRequest | None = Field(default=None, alias="methodConfig")
    sample_limit: int | None = Field(default=None, alias="sampleLimit")
    concurrency: int = 1
    timeout_seconds: int = Field(default=60, alias="timeoutSeconds")
    selected_datasource_ids: list[SnowflakeID] | None = Field(
        default=None,
        alias="selectedDatasourceIds",
    )
    source_group: str | None = Field(default=None, alias="sourceGroup")


class BenchmarkRunListQuery(_BenchmarkRequestSchema):
    page: int = 1
    page_size: int = Field(default=CHATBI_PAGE_DEFAULT_SIZE, alias="pageSize")
    dataset_id: SnowflakeID | None = Field(default=None, alias="datasetId")
    status: str | None = None


class BenchmarkCaseListQuery(_BenchmarkRequestSchema):
    page: int = 1
    page_size: int = Field(default=CHATBI_PAGE_DEFAULT_SIZE, alias="pageSize")
    status: str | None = None


class BenchmarkDatasetDatasourceUpsertRequest(_BenchmarkRequestSchema):
    datasource_id: SnowflakeID = Field(alias="datasourceId")
    db_id: str = Field(alias="dbId")
    display_name: str = Field(alias="displayName")
    status: str | None = None
    sort_order: int = Field(default=0, alias="sortOrder")


class BenchmarkDatasetOut(_BenchmarkSchema):
    id: SnowflakeID
    dataset_code: str = Field(alias="datasetCode")
    display_name: str = Field(alias="displayName")
    description: str | None
    current_version: str = Field(alias="currentVersion")
    sample_count: int = Field(alias="sampleCount")
    datasource_count: int = Field(alias="datasourceCount")
    status: str
    is_enabled: bool = Field(alias="isEnabled")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @field_serializer("created_at", "updated_at")
    def _serialize_datetime(self, value: datetime) -> str:
        return _serialize_required_datetime(value)


class BenchmarkDatasetDatasourceOut(_BenchmarkSchema):
    id: SnowflakeID
    dataset_id: SnowflakeID = Field(alias="datasetId")
    datasource_id: SnowflakeID = Field(alias="datasourceId")
    db_id: str = Field(alias="dbId")
    display_name: str = Field(alias="displayName")
    status: str
    sample_count: int = Field(alias="sampleCount")
    sort_order: int = Field(alias="sortOrder")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @field_serializer("created_at", "updated_at")
    def _serialize_datetime(self, value: datetime) -> str:
        return _serialize_required_datetime(value)


class BenchmarkMetricSummaryOut(_BenchmarkSchema):
    id: SnowflakeID
    run_id: SnowflakeID = Field(alias="runId")
    metric_name: str = Field(alias="metricName")
    metric_value: float = Field(alias="metricValue")
    sample_count: int = Field(alias="sampleCount")
    extra_json: dict[str, Any] = Field(alias="extraJson")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @field_serializer("created_at", "updated_at")
    def _serialize_datetime(self, value: datetime) -> str:
        return _serialize_required_datetime(value)


class BenchmarkRunOut(_BenchmarkSchema):
    id: SnowflakeID
    dataset_id: SnowflakeID = Field(alias="datasetId")
    dataset_code: str = Field(alias="datasetCode")
    dataset_version: str = Field(alias="datasetVersion")
    method_type: str = Field(alias="methodType")
    method_config_snapshot: dict[str, Any] = Field(alias="methodConfigSnapshot")
    selected_datasource_ids: list[SnowflakeID] | None = Field(alias="selectedDatasourceIds")
    source_group: str | None = Field(alias="sourceGroup")
    sample_limit: int | None = Field(alias="sampleLimit")
    concurrency: int
    timeout_seconds: int = Field(alias="timeoutSeconds")
    status: str
    total_count: int = Field(alias="totalCount")
    processed_count: int = Field(alias="processedCount")
    success_count: int = Field(alias="successCount")
    failed_count: int = Field(alias="failedCount")
    last_error: str | None = Field(alias="lastError")
    started_at: datetime | None = Field(alias="startedAt")
    finished_at: datetime | None = Field(alias="finishedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @field_serializer("started_at", "finished_at", "created_at", "updated_at")
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return serialize_datetime(value)

    @field_serializer("selected_datasource_ids")
    def _serialize_selected_datasource_ids(self, value: list[int] | None) -> list[str] | None:
        if value is None:
            return None
        return [str(item) for item in value]


class BenchmarkRunDetailOut(_BenchmarkSchema):
    run: BenchmarkRunOut
    metrics: list[BenchmarkMetricSummaryOut]


class BenchmarkCaseResultOut(_BenchmarkSchema):
    id: SnowflakeID
    run_id: SnowflakeID = Field(alias="runId")
    sample_id: SnowflakeID = Field(alias="sampleId")
    dataset_id: SnowflakeID = Field(alias="datasetId")
    datasource_id: SnowflakeID = Field(alias="datasourceId")
    sample_code: str = Field(alias="sampleCode")
    question_snapshot: str = Field(alias="questionSnapshot")
    gold_sql_snapshot: str = Field(alias="goldSqlSnapshot")
    generated_sql: str | None = Field(alias="generatedSql")
    execution_accuracy: float | None = Field(alias="executionAccuracy")
    table_f1: float | None = Field(alias="tableF1")
    column_f1: float | None = Field(alias="columnF1")
    join_f1: float | None = Field(alias="joinF1")
    domain_knowledge_f1: float | None = Field(alias="domainKnowledgeF1")
    status: str
    error_message: str | None = Field(alias="errorMessage")
    trace_id: str | None = Field(alias="traceId")
    detail_json: dict[str, Any] = Field(alias="detailJson")
    prompt_tokens: int | None = Field(alias="promptTokens")
    completion_tokens: int | None = Field(alias="completionTokens")
    total_tokens: int | None = Field(alias="totalTokens")
    generated_sql_execute_ms: int | None = Field(alias="generatedSqlExecuteMs")
    gold_sql_execute_ms: int | None = Field(alias="goldSqlExecuteMs")
    started_at: datetime | None = Field(alias="startedAt")
    finished_at: datetime | None = Field(alias="finishedAt")
    elapsed_ms: int | None = Field(alias="elapsedMs")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @field_serializer("detail_json")
    def _serialize_detail_json(self, value: dict[str, Any]) -> dict[str, Any]:
        return snake_to_camel_dict(value or {})

    @field_serializer("started_at", "finished_at", "created_at", "updated_at")
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return serialize_datetime(value)


class BenchmarkDatasetListResponse(_BenchmarkSchema):
    records: list[BenchmarkDatasetOut]


class BenchmarkDatasetDatasourceListResponse(_BenchmarkSchema):
    records: list[BenchmarkDatasetDatasourceOut]


class BenchmarkRunListResponse(_BenchmarkSchema):
    total: int
    current: int
    page_size: int = Field(alias="pageSize")
    records: list[BenchmarkRunOut]


class BenchmarkCaseListResponse(_BenchmarkSchema):
    total: int
    current: int
    page_size: int = Field(alias="pageSize")
    records: list[BenchmarkCaseResultOut]


class BenchmarkRerunNonSuccessOut(_BenchmarkSchema):
    submitted_count: int = Field(alias="submittedCount")
    skipped_count: int = Field(alias="skippedCount")


__all__ = [
    "BenchmarkCaseListQuery",
    "BenchmarkCaseListResponse",
    "BenchmarkCaseResultOut",
    "BenchmarkRerunNonSuccessOut",
    "BenchmarkDatasetDatasourceListResponse",
    "BenchmarkDatasetDatasourceOut",
    "BenchmarkDatasetDatasourceUpsertRequest",
    "BenchmarkDatasetListResponse",
    "BenchmarkDatasetOut",
    "BenchmarkMethodConfigRequest",
    "BenchmarkMetricSummaryOut",
    "BenchmarkRunCreateRequest",
    "BenchmarkRunDetailOut",
    "BenchmarkRunListQuery",
    "BenchmarkRunListResponse",
    "BenchmarkRunOut",
]
