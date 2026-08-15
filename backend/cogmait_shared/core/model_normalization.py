"""共享的数据模型字段规范化工具。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .coercion import parse_required_int
from .datetime_utils import parse_datetime
from .naming import camel_to_snake_dict

__all__ = [
    "normalize_bool",
    "normalize_optional_datetime",
    "normalize_optional_bool",
    "normalize_optional_int",
    "normalize_optional_positive_int",
    "normalize_optional_str",
    "normalize_non_negative_int",
    "normalize_positive_int",
    "normalize_required_str",
    "normalize_wire_payload",
]


def normalize_wire_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = camel_to_snake_dict(payload)
    if not isinstance(normalized, dict):
        raise ValueError("payload 必须为映射类型")
    return normalized


def normalize_required_str(
    raw_value: Any,
    *,
    field_name: str,
    max_length: int | None = None,
) -> str:
    if raw_value is None:
        raise ValueError(f"{field_name} 不能为空")
    if not isinstance(raw_value, str):
        raise ValueError(f"{field_name} 必须为字符串")
    value = raw_value.strip()
    if not value:
        raise ValueError(f"{field_name} 不能为空")
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"{field_name} 长度不能超过 {max_length}")
    return value


def normalize_optional_str(
    raw_value: Any,
    *,
    field_name: str = "value",
    max_length: int | None = None,
) -> str | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise ValueError(f"{field_name} 必须为字符串")
    value = raw_value.strip()
    if not value:
        return None
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"{field_name} 长度不能超过 {max_length}")
    return value


def normalize_positive_int(raw_value: Any, *, field_name: str) -> int:
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value <= 0:
        raise ValueError(f"{field_name} 必须为正整数")
    return raw_value


def normalize_non_negative_int(raw_value: Any, *, field_name: str) -> int:
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
        raise ValueError(f"{field_name} 必须为非负整数")
    return raw_value


def normalize_optional_positive_int(raw_value: Any, *, field_name: str) -> int | None:
    if raw_value is None:
        return None
    return normalize_positive_int(raw_value, field_name=field_name)


def normalize_bool(raw_value: Any, *, field_name: str) -> bool:
    if not isinstance(raw_value, bool):
        raise ValueError(f"{field_name} 必须为布尔值")
    return raw_value


def normalize_optional_bool(raw_value: Any, *, field_name: str) -> bool | None:
    if raw_value is None:
        return None
    return normalize_bool(raw_value, field_name=field_name)


def normalize_optional_int(raw_value: Any, *, field_name: str) -> int | None:
    if raw_value is None:
        return None
    return parse_required_int(raw_value, field_name=field_name)


def normalize_optional_datetime(raw_value: Any, *, field_name: str) -> datetime | None:
    if raw_value is None:
        return None
    parsed = parse_datetime(raw_value)
    if parsed is None:
        raise ValueError(f"{field_name} 格式无效")
    return parsed
