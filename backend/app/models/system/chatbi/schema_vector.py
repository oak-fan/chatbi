"""ChatBI 库表列向量 ORM 模型（pgvector）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Index, Text, text
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


class ChatbiSchemaVector(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chatbi_schema_vector"
    __table_args__ = (
        Index(
            "uq_ais_chatbi_schema_vector_ds_table_column_active",
            "datasource_id",
            "table_name",
            "column_name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        Index(
            "idx_chatbi_schema_vector_ds_deleted_table",
            "datasource_id",
            "is_deleted",
            "table_name",
        ),
        {"comment": "ChatBI 数据源 schema 列向量"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="主键",
    )
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="数据源 ID")
    table_name: Mapped[str] = mapped_column(Text, nullable=False, comment="表名")
    column_name: Mapped[str] = mapped_column(Text, nullable=False, comment="列名")
    embedding: Mapped[Any] = mapped_column(_PgVectorType(), nullable=False, comment="向量")
