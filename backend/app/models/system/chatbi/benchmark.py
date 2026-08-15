"""ChatBI 基准评价 ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from cogmait_shared.core.id_generator import generate_snowflake_id
from cogmait_shared.db import AuditSoftDeleteMixin, Base

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class ChatbiBenchmarkDataset(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chatbi_benchmark_dataset"
    __table_args__ = (
        Index(
            "uq_ais_chatbi_benchmark_dataset_code_active",
            "dataset_code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        Index(
            "idx_ais_chatbi_benchmark_dataset_enabled",
            "is_enabled",
            "status",
            "updated_at",
        ),
        {"comment": "ChatBI 基准数据集"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
    )
    dataset_code: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_version: Mapped[str] = mapped_column(String(64), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    datasource_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ChatbiBenchmarkDatasetDatasource(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chatbi_benchmark_dataset_datasource"
    __table_args__ = (
        Index(
            "uq_ais_chatbi_benchmark_dataset_datasource_active",
            "dataset_id",
            "datasource_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        Index(
            "idx_ais_chatbi_benchmark_dataset_datasource_status",
            "dataset_id",
            "status",
        ),
        Index("idx_ais_chatbi_benchmark_dataset_datasource_source", "datasource_id"),
        {"comment": "ChatBI 基准数据集与数据源关联"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
    )
    dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    db_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ChatbiBenchmarkSample(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chatbi_benchmark_sample"
    __table_args__ = (
        Index(
            "uq_ais_chatbi_benchmark_sample_active",
            "dataset_id",
            "dataset_version",
            "sample_code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        Index(
            "idx_ais_chatbi_benchmark_sample_dataset",
            "dataset_id",
            "dataset_version",
            "id",
        ),
        Index(
            "idx_ais_chatbi_benchmark_sample_datasource",
            "dataset_id",
            "datasource_id",
            "id",
        ),
        Index("idx_ais_chatbi_benchmark_sample_group", "dataset_id", "source_group", "id"),
        {"comment": "ChatBI 基准评价样本"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
    )
    sample_code: Mapped[str] = mapped_column(String(128), nullable=False)
    dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    db_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_group: Mapped[str] = mapped_column(String(128), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    gold_sql: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    ref_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ChatbiBenchmarkRun(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chatbi_benchmark_run"
    __table_args__ = (
        Index("idx_ais_chatbi_benchmark_run_user_created", "created_by", "created_at"),
        Index("idx_ais_chatbi_benchmark_run_dataset_created", "dataset_id", "created_at"),
        Index("idx_ais_chatbi_benchmark_run_status", "status", "updated_at"),
        {"comment": "ChatBI 基准评价任务"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
    )
    dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dataset_code: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    method_type: Mapped[str] = mapped_column(String(64), nullable=False)
    method_config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    selected_datasource_ids: Mapped[list[int] | None] = mapped_column(JSON_TYPE, nullable=True)
    source_group: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sample_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatbiBenchmarkCaseResult(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chatbi_benchmark_case_result"
    __table_args__ = (
        Index(
            "uq_ais_chatbi_benchmark_case_result_active",
            "run_id",
            "sample_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        Index("idx_ais_chatbi_benchmark_case_result_status", "run_id", "status"),
        Index("idx_ais_chatbi_benchmark_case_result_sample", "sample_id", "created_at"),
        Index(
            "idx_ais_chatbi_benchmark_case_result_datasource",
            "run_id",
            "datasource_id",
        ),
        {"comment": "ChatBI 基准评价样本结果"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
    )
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sample_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dataset_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sample_code: Mapped[str] = mapped_column(String(128), nullable=False)
    question_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    gold_sql_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    generated_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_accuracy: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    table_f1: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    column_f1: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    join_f1: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    domain_knowledge_f1: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detail_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generated_sql_execute_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gold_sql_execute_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ChatbiBenchmarkMetricSummary(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chatbi_benchmark_metric_summary"
    __table_args__ = (
        Index(
            "uq_ais_chatbi_benchmark_summary_active",
            "run_id",
            "metric_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        {"comment": "ChatBI 基准评价聚合指标"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
    )
    run_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_value: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    extra_json: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)


__all__ = [
    "ChatbiBenchmarkCaseResult",
    "ChatbiBenchmarkDataset",
    "ChatbiBenchmarkDatasetDatasource",
    "ChatbiBenchmarkMetricSummary",
    "ChatbiBenchmarkRun",
    "ChatbiBenchmarkSample",
]
