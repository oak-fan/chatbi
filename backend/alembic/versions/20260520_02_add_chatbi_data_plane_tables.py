"""ChatBI 数据面表：query_log、qsql、业务知识及向量表。

Revision ID: 20260520_02
Revises: 20260520_01
Create Date: 2026-05-20 11:00:00
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

from app.core.config import settings

revision = "20260520_02"
down_revision = "20260520_01"
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
        "ais_chatbi_query_log",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=False,
            comment="问数日志 ID",
        ),
        sa.Column("assistant_message_id", sa.BigInteger(), nullable=False, comment="助手消息 ID"),
        sa.Column("user_message_id", sa.BigInteger(), nullable=True, comment="用户消息 ID"),
        sa.Column("request_id", sa.String(length=64), nullable=True, comment="请求链路 ID"),
        sa.Column("datasource_id", sa.BigInteger(), nullable=True, comment="数据源 ID"),
        sa.Column("user_question", sa.Text(), nullable=False, comment="用户原始问题"),
        sa.Column("rewritten_question", sa.Text(), nullable=True, comment="改写后问题"),
        sa.Column("intent", sa.Text(), nullable=True, comment="意图 JSON"),
        sa.Column("final_sql", sa.Text(), nullable=True, comment="最终 SQL"),
        sa.Column("result_preview", JSON_TYPE, nullable=True, comment="结果预览"),
        sa.Column("latency_ms", sa.Integer(), nullable=True, comment="总耗时毫秒"),
        sa.Column(
            "meta",
            JSON_TYPE,
            nullable=False,
            server_default=sa.text("'{}'"),
            comment="扩展元数据",
        ),
        *_audit_columns(),
        comment="ChatBI 问数日志",
    )
    op.create_index(
        "uq_chatbi_log_assistant_msg",
        "ais_chatbi_query_log",
        ["assistant_message_id"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
    )
    op.create_index(
        "idx_chatbi_log_ds_created",
        "ais_chatbi_query_log",
        ["datasource_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_chatbi_log_user_created",
        "ais_chatbi_query_log",
        ["created_by", "created_at"],
        unique=False,
    )

    op.create_table(
        "ais_chatbi_qsql",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=False,
            comment="Q-SQL ID",
        ),
        sa.Column("datasource_id", sa.BigInteger(), nullable=False, comment="数据源 ID"),
        sa.Column("question", sa.Text(), nullable=False, comment="自然语言问题"),
        sa.Column("sql_body", sa.Text(), nullable=False, comment="SQL 正文"),
        sa.Column("llm_simplified_description", sa.Text(), nullable=True, comment="LLM 简述"),
        *_audit_columns(),
        comment="ChatBI Q-SQL 样例",
    )
    op.create_index(
        "idx_chatbi_qsql_ds_created",
        "ais_chatbi_qsql",
        ["datasource_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "ais_chatbi_qsql_vector",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=False,
            comment="主键",
        ),
        sa.Column("qsql_id", sa.BigInteger(), nullable=False, comment="Q-SQL ID"),
        sa.Column("datasource_id", sa.BigInteger(), nullable=False, comment="数据源 ID"),
        sa.Column("embedding", PgVectorType(), nullable=False, comment="向量"),
        *_audit_columns(),
        comment="ChatBI Q-SQL 向量",
    )
    op.create_index(
        "idx_chatbi_qsql_vector_ds_deleted",
        "ais_chatbi_qsql_vector",
        ["datasource_id", "is_deleted", "qsql_id"],
        unique=False,
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ais_chatbi_qsql_vector_embedding_cosine "
        "ON ais_chatbi_qsql_vector USING ivfflat (embedding vector_cosine_ops) "
        f"WITH (lists = {_resolve_vector_ivfflat_lists()})"
    )

    op.create_table(
        "ais_chatbi_business_knowledge",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=False,
            comment="业务知识 ID",
        ),
        sa.Column("content", sa.Text(), nullable=False, comment="知识正文"),
        sa.Column("scope", sa.String(length=32), nullable=False, comment="作用域"),
        sa.Column("kind", sa.String(length=32), nullable=False, comment="知识类型"),
        sa.Column("datasource_id", sa.BigInteger(), nullable=False, comment="数据源 ID"),
        *_audit_columns(),
        comment="ChatBI 业务知识",
    )
    op.create_index(
        "idx_chatbi_bizkn_scope_kind",
        "ais_chatbi_business_knowledge",
        ["scope", "kind", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_chatbi_bizkn_ds_created",
        "ais_chatbi_business_knowledge",
        ["datasource_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_chatbi_bizkn_deleted_created",
        "ais_chatbi_business_knowledge",
        ["is_deleted", "created_at", "id"],
        unique=False,
    )

    op.create_table(
        "ais_chatbi_business_knowledge_vector",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=False,
            comment="主键",
        ),
        sa.Column("business_knowledge_id", sa.BigInteger(), nullable=False, comment="业务知识 ID"),
        sa.Column("datasource_id", sa.BigInteger(), nullable=False, comment="数据源 ID"),
        sa.Column("embedding", PgVectorType(), nullable=False, comment="向量"),
        *_audit_columns(),
        comment="ChatBI 业务知识向量",
    )
    op.create_index(
        "idx_chatbi_bizkn_vector_deleted_id",
        "ais_chatbi_business_knowledge_vector",
        ["is_deleted", "business_knowledge_id"],
        unique=False,
    )
    op.create_index(
        "idx_chatbi_bizkn_vector_ds_deleted",
        "ais_chatbi_business_knowledge_vector",
        ["datasource_id", "is_deleted"],
        unique=False,
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ais_chatbi_bizkn_vector_embedding_cosine "
        "ON ais_chatbi_business_knowledge_vector USING ivfflat (embedding vector_cosine_ops) "
        f"WITH (lists = {_resolve_vector_ivfflat_lists()})"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_ais_chatbi_bizkn_vector_embedding_cosine")
    op.drop_index(
        "idx_chatbi_bizkn_vector_deleted_id",
        table_name="ais_chatbi_business_knowledge_vector",
    )
    op.drop_index(
        "idx_chatbi_bizkn_vector_ds_deleted",
        table_name="ais_chatbi_business_knowledge_vector",
    )
    op.drop_table("ais_chatbi_business_knowledge_vector")
    op.drop_index("idx_chatbi_bizkn_deleted_created", table_name="ais_chatbi_business_knowledge")
    op.drop_index("idx_chatbi_bizkn_ds_created", table_name="ais_chatbi_business_knowledge")
    op.drop_index("idx_chatbi_bizkn_scope_kind", table_name="ais_chatbi_business_knowledge")
    op.drop_table("ais_chatbi_business_knowledge")
    op.execute("DROP INDEX IF EXISTS idx_ais_chatbi_qsql_vector_embedding_cosine")
    op.drop_index("idx_chatbi_qsql_vector_ds_deleted", table_name="ais_chatbi_qsql_vector")
    op.drop_table("ais_chatbi_qsql_vector")
    op.drop_index("idx_chatbi_qsql_ds_created", table_name="ais_chatbi_qsql")
    op.drop_table("ais_chatbi_qsql")
    op.drop_index("idx_chatbi_log_user_created", table_name="ais_chatbi_query_log")
    op.drop_index("idx_chatbi_log_ds_created", table_name="ais_chatbi_query_log")
    op.drop_index("uq_chatbi_log_assistant_msg", table_name="ais_chatbi_query_log")
    op.drop_table("ais_chatbi_query_log")
