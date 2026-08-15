"""新增 ChatBI 基准评价表。

Revision ID: 20260610_01
Revises: 20260524_03
Create Date: 2026-06-10 11:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260610_01"
down_revision = "20260524_03"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _audit_columns() -> list[sa.Column]:
    return [
        sa.Column("created_by", sa.BigInteger(), nullable=True, comment="创建人"),
        sa.Column("updated_by", sa.BigInteger(), nullable=True, comment="更新人"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="创建时间",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="更新时间",
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
            comment="删除标记",
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "ais_chatbi_benchmark_dataset",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("dataset_code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("current_version", sa.String(length=64), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("datasource_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_audit_columns(),
        comment="ChatBI 基准数据集",
    )
    op.create_index(
        "uq_ais_chatbi_benchmark_dataset_code_active",
        "ais_chatbi_benchmark_dataset",
        ["dataset_code"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "idx_ais_chatbi_benchmark_dataset_enabled",
        "ais_chatbi_benchmark_dataset",
        ["is_enabled", "status", "updated_at"],
    )

    op.create_table(
        "ais_chatbi_benchmark_dataset_datasource",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("dataset_id", sa.BigInteger(), nullable=False),
        sa.Column("datasource_id", sa.BigInteger(), nullable=False),
        sa.Column("db_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        *_audit_columns(),
        comment="ChatBI 基准数据集与数据源关联",
    )
    op.create_index(
        "uq_ais_chatbi_benchmark_dataset_datasource_active",
        "ais_chatbi_benchmark_dataset_datasource",
        ["dataset_id", "datasource_id"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "idx_ais_chatbi_benchmark_dataset_datasource_status",
        "ais_chatbi_benchmark_dataset_datasource",
        ["dataset_id", "status"],
    )
    op.create_index(
        "idx_ais_chatbi_benchmark_dataset_datasource_source",
        "ais_chatbi_benchmark_dataset_datasource",
        ["datasource_id"],
    )

    op.create_table(
        "ais_chatbi_benchmark_sample",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("sample_code", sa.String(length=128), nullable=False),
        sa.Column("dataset_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("datasource_id", sa.BigInteger(), nullable=False),
        sa.Column("db_id", sa.String(length=128), nullable=False),
        sa.Column("source_group", sa.String(length=128), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("gold_sql", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("ref_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        *_audit_columns(),
        comment="ChatBI 基准评价样本",
    )
    op.create_index(
        "uq_ais_chatbi_benchmark_sample_active",
        "ais_chatbi_benchmark_sample",
        ["dataset_id", "dataset_version", "sample_code"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "idx_ais_chatbi_benchmark_sample_dataset",
        "ais_chatbi_benchmark_sample",
        ["dataset_id", "dataset_version", "id"],
    )
    op.create_index(
        "idx_ais_chatbi_benchmark_sample_datasource",
        "ais_chatbi_benchmark_sample",
        ["dataset_id", "datasource_id", "id"],
    )
    op.create_index(
        "idx_ais_chatbi_benchmark_sample_group",
        "ais_chatbi_benchmark_sample",
        ["dataset_id", "source_group", "id"],
    )

    op.create_table(
        "ais_chatbi_benchmark_run",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("dataset_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_code", sa.String(length=64), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=False),
        sa.Column("method_type", sa.String(length=64), nullable=False),
        sa.Column("method_config_snapshot", JSON_TYPE, nullable=False),
        sa.Column("selected_datasource_ids", JSON_TYPE, nullable=True),
        sa.Column("source_group", sa.String(length=128), nullable=True),
        sa.Column("sample_limit", sa.Integer(), nullable=True),
        sa.Column("concurrency", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_audit_columns(),
        comment="ChatBI 基准评价任务",
    )
    op.create_index(
        "idx_ais_chatbi_benchmark_run_user_created",
        "ais_chatbi_benchmark_run",
        ["created_by", "created_at"],
    )
    op.create_index(
        "idx_ais_chatbi_benchmark_run_dataset_created",
        "ais_chatbi_benchmark_run",
        ["dataset_id", "created_at"],
    )
    op.create_index(
        "idx_ais_chatbi_benchmark_run_status",
        "ais_chatbi_benchmark_run",
        ["status", "updated_at"],
    )

    op.create_table(
        "ais_chatbi_benchmark_case_result",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("sample_id", sa.BigInteger(), nullable=False),
        sa.Column("dataset_id", sa.BigInteger(), nullable=False),
        sa.Column("datasource_id", sa.BigInteger(), nullable=False),
        sa.Column("sample_code", sa.String(length=128), nullable=False),
        sa.Column("question_snapshot", sa.Text(), nullable=False),
        sa.Column("gold_sql_snapshot", sa.Text(), nullable=False),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("execution_accuracy", sa.Numeric(5, 4), nullable=True),
        sa.Column("table_f1", sa.Numeric(5, 4), nullable=True),
        sa.Column("column_f1", sa.Numeric(5, 4), nullable=True),
        sa.Column("join_f1", sa.Numeric(5, 4), nullable=True),
        sa.Column("domain_knowledge_f1", sa.Numeric(5, 4), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("detail_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("generated_sql_execute_ms", sa.Integer(), nullable=True),
        sa.Column("gold_sql_execute_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        *_audit_columns(),
        comment="ChatBI 基准评价样本结果",
    )
    op.create_index(
        "uq_ais_chatbi_benchmark_case_result_active",
        "ais_chatbi_benchmark_case_result",
        ["run_id", "sample_id"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "idx_ais_chatbi_benchmark_case_result_status",
        "ais_chatbi_benchmark_case_result",
        ["run_id", "status"],
    )
    op.create_index(
        "idx_ais_chatbi_benchmark_case_result_sample",
        "ais_chatbi_benchmark_case_result",
        ["sample_id", "created_at"],
    )
    op.create_index(
        "idx_ais_chatbi_benchmark_case_result_datasource",
        "ais_chatbi_benchmark_case_result",
        ["run_id", "datasource_id"],
    )

    op.create_table(
        "ais_chatbi_benchmark_metric_summary",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("metric_name", sa.String(length=64), nullable=False),
        sa.Column("metric_value", sa.Numeric(8, 6), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("extra_json", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        *_audit_columns(),
        comment="ChatBI 基准评价聚合指标",
    )
    op.create_index(
        "uq_ais_chatbi_benchmark_summary_active",
        "ais_chatbi_benchmark_metric_summary",
        ["run_id", "metric_name"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_ais_chatbi_benchmark_summary_active",
        table_name="ais_chatbi_benchmark_metric_summary",
    )
    op.drop_table("ais_chatbi_benchmark_metric_summary")

    op.drop_index(
        "idx_ais_chatbi_benchmark_case_result_datasource",
        table_name="ais_chatbi_benchmark_case_result",
    )
    op.drop_index(
        "idx_ais_chatbi_benchmark_case_result_sample",
        table_name="ais_chatbi_benchmark_case_result",
    )
    op.drop_index(
        "idx_ais_chatbi_benchmark_case_result_status",
        table_name="ais_chatbi_benchmark_case_result",
    )
    op.drop_index(
        "uq_ais_chatbi_benchmark_case_result_active",
        table_name="ais_chatbi_benchmark_case_result",
    )
    op.drop_table("ais_chatbi_benchmark_case_result")

    op.drop_index("idx_ais_chatbi_benchmark_run_status", table_name="ais_chatbi_benchmark_run")
    op.drop_index(
        "idx_ais_chatbi_benchmark_run_dataset_created",
        table_name="ais_chatbi_benchmark_run",
    )
    op.drop_index(
        "idx_ais_chatbi_benchmark_run_user_created",
        table_name="ais_chatbi_benchmark_run",
    )
    op.drop_table("ais_chatbi_benchmark_run")

    op.drop_index("idx_ais_chatbi_benchmark_sample_group", table_name="ais_chatbi_benchmark_sample")
    op.drop_index(
        "idx_ais_chatbi_benchmark_sample_datasource",
        table_name="ais_chatbi_benchmark_sample",
    )
    op.drop_index(
        "idx_ais_chatbi_benchmark_sample_dataset",
        table_name="ais_chatbi_benchmark_sample",
    )
    op.drop_index(
        "uq_ais_chatbi_benchmark_sample_active",
        table_name="ais_chatbi_benchmark_sample",
    )
    op.drop_table("ais_chatbi_benchmark_sample")

    op.drop_index(
        "idx_ais_chatbi_benchmark_dataset_datasource_source",
        table_name="ais_chatbi_benchmark_dataset_datasource",
    )
    op.drop_index(
        "idx_ais_chatbi_benchmark_dataset_datasource_status",
        table_name="ais_chatbi_benchmark_dataset_datasource",
    )
    op.drop_index(
        "uq_ais_chatbi_benchmark_dataset_datasource_active",
        table_name="ais_chatbi_benchmark_dataset_datasource",
    )
    op.drop_table("ais_chatbi_benchmark_dataset_datasource")

    op.drop_index(
        "idx_ais_chatbi_benchmark_dataset_enabled",
        table_name="ais_chatbi_benchmark_dataset",
    )
    op.drop_index(
        "uq_ais_chatbi_benchmark_dataset_code_active",
        table_name="ais_chatbi_benchmark_dataset",
    )
    op.drop_table("ais_chatbi_benchmark_dataset")
