"""枚举解析内部工具。"""

from __future__ import annotations

from enum import IntEnum
from typing import TypeVar

from cogmait_shared.core.coercion import parse_strict_int

E = TypeVar("E", bound=IntEnum)


def enum_from_value(enum_cls: type[E], value: int | str | E) -> E:
    """将 int/str/枚举实例解析为目标 IntEnum。"""
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in enum_cls.__members__:
            return enum_cls[normalized]
        value = normalized

    parsed = parse_strict_int(value)
    if parsed is None:
        raise ValueError(f"invalid {enum_cls.__name__} value: {value}")
    return enum_cls(parsed)
