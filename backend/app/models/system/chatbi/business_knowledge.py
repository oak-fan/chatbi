"""ChatBI 业务知识 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cogmait_shared.core.id_generator import generate_snowflake_id
from cogmait_shared.db import AuditSoftDeleteMixin, Base


class ChatbiBusinessKnowledge(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chatbi_business_knowledge"
    __table_args__ = (
        Index("idx_chatbi_bizkn_scope_kind", "scope", "kind", "created_at"),
        Index("idx_chatbi_bizkn_ds_created", "datasource_id", "created_at"),
        Index("idx_chatbi_bizkn_deleted_created", "is_deleted", "created_at", "id"),
        {"comment": "ChatBI 业务知识"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="业务知识 ID",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="知识正文")
    scope: Mapped[str] = mapped_column(String(32), nullable=False, comment="作用域")
    kind: Mapped[str] = mapped_column(String(32), nullable=False, comment="知识类型")
    datasource_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="数据源 ID",
    )
