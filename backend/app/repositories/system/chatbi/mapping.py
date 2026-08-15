"""ChatBI 仓储 ORM → Domain Record 映射辅助。"""

from __future__ import annotations

from datetime import datetime


def require_datetime(value: datetime | None) -> datetime:
    """ORM 审计时间戳在已持久化行上不应为空。"""
    if value is None:
        msg = "时间戳缺失"
        raise ValueError(msg)
    return value


__all__ = ["require_datetime"]
