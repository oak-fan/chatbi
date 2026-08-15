"""ChatBI 任务 ORM 模型。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from cogmait_shared.core.id_generator import generate_snowflake_id
from cogmait_shared.db import AuditSoftDeleteMixin, Base

from ....constants.chatbi.task import CHATBI_ACTIVE_TASK_STATUS_SQL


class ChatbiTask(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chatbi_task"
    __table_args__ = (
        Index(
            "idx_ais_chatbi_task_datasource_status_id",
            "datasource_id",
            "status",
            "id",
        ),
        Index(
            "uq_ais_chatbi_task_datasource_active",
            "datasource_id",
            unique=True,
            postgresql_where=text(f"{CHATBI_ACTIVE_TASK_STATUS_SQL} AND is_deleted = false"),
            sqlite_where=text(f"{CHATBI_ACTIVE_TASK_STATUS_SQL} AND is_deleted = 0"),
        ),
        {"comment": "ChatBI 预处理任务"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="任务 ID",
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="任务类型")
    status: Mapped[str] = mapped_column(String(32), nullable=False, comment="任务状态")
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="数据源 ID")
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="总步骤")
    processed_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="已完成步骤",
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
        comment="任务上下文",
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="最近错误")
