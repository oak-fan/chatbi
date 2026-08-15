"""ChatBI 问数日志 ORM 模型。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from cogmait_shared.core.id_generator import generate_snowflake_id
from cogmait_shared.db import AuditSoftDeleteMixin, Base


class ChatbiQueryLog(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chatbi_query_log"
    __table_args__ = (
        Index(
            "uq_chatbi_log_assistant_msg",
            "assistant_message_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        Index("idx_chatbi_log_ds_created", "datasource_id", "created_at"),
        Index("idx_chatbi_log_user_created", "created_by", "created_at"),
        {"comment": "ChatBI 问数日志"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="问数日志 ID",
    )
    assistant_message_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="助手消息 ID",
    )
    user_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="用户消息 ID",
    )
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="请求 ID")
    datasource_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="数据源 ID",
    )
    user_question: Mapped[str] = mapped_column(Text, nullable=False, comment="用户原始问题")
    rewritten_question: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="改写后问题",
    )
    intent: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="意图分类")
    final_sql: Mapped[str | None] = mapped_column(Text, nullable=True, comment="最终 SQL")
    result_preview: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
        comment="结果预览",
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="总耗时毫秒")
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
        comment="扩展元数据",
    )
