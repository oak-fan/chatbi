"""ChatBI 数据源域表结构 Alembic 迁移。

Revision ID: 20260520_01
Revises: 20260517_01
Create Date: 2026-05-20 10:00:00
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

from app.core.config import settings

revision = "20260520_01"
down_revision = None
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
DEFAULT_VECTOR_DIMENSIONS = 1024
DEFAULT_VECTOR_IVFFLAT_LISTS = 100


def _settings_int(name: str, default: int) -> int:
    value = getattr(settings, name, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class PgVectorType(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int | None = None) -> None:
        self._dimensions = dimensions or DEFAULT_VECTOR_DIMENSIONS

    def get_col_spec(self, **_: Any) -> str:
        return f"vector({self._dimensions})"


def _resolve_vector_ivfflat_lists() -> int:
    return _settings_int("vector_postgres_ivfflat_lists", DEFAULT_VECTOR_IVFFLAT_LISTS)


def _audit_columns() -> list[Any]:
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
            comment="删除标记: false=正常,true=已删除",
        ),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "ais_chatbi_datasource",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=False,
            comment="数据源 ID",
        ),
        sa.Column("origin", sa.String(length=32), nullable=False, comment="来源"),
        sa.Column("name", sa.String(length=128), nullable=False, comment="配置名称"),
        sa.Column("type", sa.String(length=32), nullable=False, comment="数据库类型"),
        sa.Column("host", sa.String(length=255), nullable=False, comment="主机"),
        sa.Column("port", sa.Integer(), nullable=False, comment="端口"),
        sa.Column("database", sa.String(length=128), nullable=False, comment="数据库名"),
        sa.Column("schema_name", sa.String(length=63), nullable=True, comment="PostgreSQL schema"),
        sa.Column("username", sa.String(length=128), nullable=False, comment="用户名"),
        sa.Column("password", sa.String(length=512), nullable=False, comment="密码密文"),
        sa.Column("import_file_ids", JSON_TYPE, nullable=True, comment="上传文件 id 列表"),
        sa.Column("db_schema", JSON_TYPE, nullable=True, comment="结构快照"),
        sa.Column(
            "db_schema_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="快照更新时间",
        ),
        sa.Column("extra_params", JSON_TYPE, nullable=True, comment="连接附加参数"),
        sa.Column("remark", sa.String(length=255), nullable=True, comment="备注"),
        *_audit_columns(),
        comment="ChatBI 数据源",
    )
    op.create_index(
        "idx_chatbi_datasource_name",
        "ais_chatbi_datasource",
        ["name"],
        unique=False,
    )
    op.create_index(
        "idx_chatbi_datasource_type",
        "ais_chatbi_datasource",
        ["type"],
        unique=False,
    )
    op.create_index(
        "uq_ais_chatbi_datasource_name_active",
        "ais_chatbi_datasource",
        ["name"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )

    op.create_table(
        "ais_chatbi_task",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=False,
            comment="任务 ID",
        ),
        sa.Column("task_type", sa.String(length=64), nullable=False, comment="任务类型"),
        sa.Column("status", sa.String(length=32), nullable=False, comment="任务状态"),
        sa.Column("datasource_id", sa.BigInteger(), nullable=False, comment="数据源 ID"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("payload", JSON_TYPE, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_error", sa.Text(), nullable=True, comment="最近错误"),
        *_audit_columns(),
        comment="ChatBI 预处理任务",
    )
    op.create_index(
        "idx_ais_chatbi_task_datasource_status_id",
        "ais_chatbi_task",
        ["datasource_id", "status", "id"],
        unique=False,
    )
    op.create_index(
        "uq_ais_chatbi_task_datasource_active",
        "ais_chatbi_task",
        ["datasource_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'RUNNING') AND is_deleted = false"),
    )

    op.create_table(
        "ais_chatbi_schema_vector",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False, comment="主键"),
        sa.Column("datasource_id", sa.BigInteger(), nullable=False, comment="数据源 ID"),
        sa.Column("table_name", sa.Text(), nullable=False, comment="表名"),
        sa.Column("column_name", sa.Text(), nullable=False, comment="列名"),
        sa.Column("embedding", PgVectorType(), nullable=False, comment="向量"),
        *_audit_columns(),
        comment="ChatBI 数据源 schema 列向量",
    )
    op.create_index(
        "idx_chatbi_schema_vector_ds_deleted_table",
        "ais_chatbi_schema_vector",
        ["datasource_id", "is_deleted", "table_name"],
        unique=False,
    )
    op.create_index(
        "uq_ais_chatbi_schema_vector_ds_table_column_active",
        "ais_chatbi_schema_vector",
        ["datasource_id", "table_name", "column_name"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ais_chatbi_schema_vector_embedding_cosine "
        "ON ais_chatbi_schema_vector USING ivfflat (embedding vector_cosine_ops) "
        f"WITH (lists = {_resolve_vector_ivfflat_lists()})"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ais_chatbi_schema_vector_embedding_cosine")
    op.drop_index(
        "uq_ais_chatbi_schema_vector_ds_table_column_active",
        table_name="ais_chatbi_schema_vector",
    )
    op.drop_index(
        "idx_chatbi_schema_vector_ds_deleted_table",
        table_name="ais_chatbi_schema_vector",
    )
    op.drop_table("ais_chatbi_schema_vector")

    op.drop_index("uq_ais_chatbi_task_datasource_active", table_name="ais_chatbi_task")
    op.drop_index("idx_ais_chatbi_task_datasource_status_id", table_name="ais_chatbi_task")
    op.drop_table("ais_chatbi_task")

    op.drop_index("uq_ais_chatbi_datasource_name_active", table_name="ais_chatbi_datasource")
    op.drop_index("idx_chatbi_datasource_type", table_name="ais_chatbi_datasource")
    op.drop_index("idx_chatbi_datasource_name", table_name="ais_chatbi_datasource")
    op.drop_table("ais_chatbi_datasource")
