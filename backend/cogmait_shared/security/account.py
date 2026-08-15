"""共享账户类型技术契约。"""

from __future__ import annotations

from enum import StrEnum


class AccountType(StrEnum):
    """后台入口账号类型。"""

    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"

    @classmethod
    def normalize(cls, value: object) -> str | None:
        if isinstance(value, cls):
            return value.value
        if isinstance(value, bool):
            return None
        if not isinstance(value, str):
            return None
        normalized = value.strip().upper()
        return normalized if normalized in cls._value2member_map_ else None

    @classmethod
    def is_super_admin(cls, value: object) -> bool:
        return cls.normalize(value) == cls.SUPER_ADMIN.value

    @classmethod
    def is_admin(cls, value: object) -> bool:
        return cls.normalize(value) == cls.ADMIN.value


__all__ = ["AccountType"]
