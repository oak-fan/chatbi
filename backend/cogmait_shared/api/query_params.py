"""API 查询参数解析工具。"""

from __future__ import annotations

from typing import Any


def parse_query_bool(value: Any, *, field_name: str) -> bool:
    """解析仅允许 true/false 文本的查询参数布尔值。"""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    raise ValueError(f"{field_name} 仅支持 true/false")


def parse_optional_query_bool(value: Any, *, field_name: str) -> bool | None:
    """解析可缺省的 true/false 查询参数布尔值。"""

    if value is None:
        return None
    return parse_query_bool(value, field_name=field_name)


__all__ = ["parse_optional_query_bool", "parse_query_bool"]
