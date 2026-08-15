"""ChatBI 数据源 ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from cogmait_shared.core.id_generator import generate_snowflake_id
from cogmait_shared.db import AuditSoftDeleteMixin, Base


class ChatbiDatasource(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chatbi_datasource"
    __table_args__ = (
        Index(
            "uq_ais_chatbi_datasource_owner_name_active",
            "created_by",
            "name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        Index("idx_chatbi_datasource_name", "name"),
        Index("idx_chatbi_datasource_connector_type", "connector_type"),
        {"comment": "ChatBI 数据源"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="数据源 ID",
    )
    origin: Mapped[str] = mapped_column(String(32), nullable=False, comment="来源")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="配置名称")
    connector_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="数据库类型")
    host: Mapped[str] = mapped_column(String(255), nullable=False, comment="主机")
    port: Mapped[int] = mapped_column(Integer, nullable=False, comment="端口")
    database: Mapped[str] = mapped_column(String(128), nullable=False, comment="数据库名")
    schema_name: Mapped[str | None] = mapped_column(String(63), nullable=True, comment="PG schema")
    username: Mapped[str] = mapped_column(String(128), nullable=False, comment="用户名")
    password: Mapped[str] = mapped_column(String(512), nullable=False, comment="密码密文")
    import_file_ids: Mapped[list[Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
        comment="上传文件 id",
    )
    db_schema: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
        comment="结构快照",
    )
    db_schema_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="快照更新时间",
    )
    extra_params: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
        comment="连接附加参数",
    )
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="备注")
