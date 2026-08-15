"""字典/字典项相关枚举定义。"""

from __future__ import annotations

from enum import Enum, StrEnum

__all__ = ["DictState", "DictConfigType"]


class DictState(Enum):
    """字典、字典项状态。"""

    ENABLED = True
    DISABLED = False

    @property
    def is_enabled(self) -> bool:
        return self is DictState.ENABLED

    @classmethod
    def from_value(cls, value: bool | str | DictState) -> DictState:
        if isinstance(value, cls):
            return value
        if isinstance(value, bool):
            return cls.ENABLED if value else cls.DISABLED
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized in cls.__members__:
                return cls[normalized]
        raise ValueError(f"invalid {cls.__name__} value: {value}")


class DictConfigType(StrEnum):
    """字典配置类型：系统 / 业务。"""

    SYSTEM = "SYSTEM"
    BUSINESS = "BUSINESS"

    @classmethod
    def from_value(cls, value: str | DictConfigType) -> DictConfigType:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized in cls.__members__:
                return cls[normalized]
        raise ValueError(f"invalid {cls.__name__} value: {value}")
