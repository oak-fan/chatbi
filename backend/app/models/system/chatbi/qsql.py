"""ChatBI Q-SQL ORM 模型。"""

from __future__ import annotations

from sqlalchemy import BigInteger, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from cogmait_shared.core.id_generator import generate_snowflake_id
from cogmait_shared.db import AuditSoftDeleteMixin, Base

from ....domain.system.chatbi.qsql import QSQL_SCOPE_DATASOURCE


class ChatbiQsql(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chatbi_qsql"
    __table_args__ = (
        Index("idx_chatbi_qsql_ds_created", "datasource_id", "created_at"),
        Index("idx_chatbi_qsql_scope_source", "scope", "source_dataset", "source_db_id"),
        Index("idx_chatbi_qsql_source_sample", "source_dataset", "source_sample_id"),
        {"comment": "ChatBI Q-SQL 样例"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="Q-SQL ID",
    )
    datasource_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="数据源 ID")
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="自然语言问题")
    sql_body: Mapped[str] = mapped_column(Text, nullable=False, comment="SQL 正文")
    llm_simplified_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="LLM 生成的 SQL 简述",
    )
    scope: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=QSQL_SCOPE_DATASOURCE,
        comment="Q-SQL 作用域：DATASOURCE/GLOBAL",
    )
    source_dataset: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="外部样例来源数据集",
    )
    source_db_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="外部样例原始 db_id",
    )
    source_sample_id: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment="外部样例稳定 ID",
    )
    sql_skeleton: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="DAIL-SQL SQL skeleton",
    )
