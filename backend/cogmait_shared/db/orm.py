"""跨服务共享的 ORM 基类与审计字段。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """公共 Declarative 基类。"""


class TimestampMixin:
    """通用创建/更新时间字段。"""

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )


class OperatorAuditMixin:
    """通用创建人/更新人字段。"""

    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="创建人")
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="更新人")


class SoftDeleteMixin:
    """通用逻辑删除标记字段。"""

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="删除标记: false=正常,true=已删除",
    )


class AuditSoftDeleteMixin(OperatorAuditMixin, TimestampMixin, SoftDeleteMixin):
    """组合审计字段：创建/更新人、创建/更新时间、逻辑删除标记。"""


__all__ = [
    "Base",
    "TimestampMixin",
    "OperatorAuditMixin",
    "SoftDeleteMixin",
    "AuditSoftDeleteMixin",
]
