"""ChatBI 业务知识向量 ORM 模型。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

from cogmait_shared.core.id_generator import generate_snowflake_id
from cogmait_shared.db import AuditSoftDeleteMixin, Base

from ....constants.chatbi.datasource import CHATBI_VECTOR_DIMENSIONS


class _PgVectorType(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int | None = None) -> None:
        self._dimensions = dimensions or CHATBI_VECTOR_DIMENSIONS

    def get_col_spec(self, **_: Any) -> str:
        return f"vector({self._dimensions})"

    def copy(self, **_: Any) -> _PgVectorType:
        return _PgVectorType(self._dimensions)


class ChatbiBusinessKnowledgeVector(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chatbi_business_knowledge_vector"
    __table_args__ = (
        Index("idx_chatbi_bizkn_vector_deleted_id", "is_deleted", "business_knowledge_id"),
        Index("idx_chatbi_bizkn_vector_ds_deleted", "datasource_id", "is_deleted"),
        {"comment": "ChatBI 业务知识向量"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="主键",
    )
    business_knowledge_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="业务知识 ID",
    )
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="数据源 ID")
    embedding: Mapped[Any] = mapped_column(_PgVectorType(), nullable=False, comment="向量")
