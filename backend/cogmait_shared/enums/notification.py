"""通知相关枚举。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

MAX_NOTIFICATION_SOURCE_CODE_LENGTH = 64


class NotificationSourceCode(StrEnum):
    """内置通知来源编码。"""

    SYSTEM = "SYSTEM"


def normalize_notification_source_code(value: Any) -> str:
    """规范化通知来源编码，允许服务按同一格式扩展自有来源。"""
    if isinstance(value, NotificationSourceCode):
        normalized = value.value
    elif isinstance(value, str):
        normalized = value.strip().upper()
    else:
        raise ValueError("通知来源必须为字符串")
    if not normalized:
        raise ValueError("通知来源不能为空")
    if len(normalized) > MAX_NOTIFICATION_SOURCE_CODE_LENGTH:
        raise ValueError(f"通知来源长度不能超过 {MAX_NOTIFICATION_SOURCE_CODE_LENGTH} 字符")
    if not normalized.replace("_", "").isalnum() or not normalized[0].isalpha():
        raise ValueError("通知来源格式不正确")
    return normalized


__all__ = [
    "MAX_NOTIFICATION_SOURCE_CODE_LENGTH",
    "NotificationSourceCode",
    "normalize_notification_source_code",
]
