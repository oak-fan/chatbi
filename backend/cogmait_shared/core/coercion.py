"""共享类型规范化工具。"""

from __future__ import annotations

from typing import Any

__all__ = ["parse_required_int", "parse_strict_int", "parse_strict_bool"]

_TRUE_BOOL_TEXTS = {"1", "true", "yes", "on"}
_FALSE_BOOL_TEXTS = {"0", "false", "no", "off"}


def parse_strict_int(raw_value: Any) -> int | None:
    """严格解析整数，失败时返回 ``None``。"""
    normalized = _normalize_int_candidate(raw_value)
    if normalized is None:
        return None
    if isinstance(normalized, int):
        return normalized
    if normalized[0] in {"+", "-"}:
        digits = normalized[1:]
        if not digits.isdigit():
            return None
    elif not normalized.isdigit():
        return None
    return int(normalized)


def _normalize_int_candidate(raw_value: Any) -> str | int | None:
    if raw_value is None or isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, bytes | bytearray):
        try:
            raw_value = raw_value.decode()
        except UnicodeDecodeError:
            return None
    if not isinstance(raw_value, str):
        return None
    normalized = raw_value.strip()
    if not normalized:
        return None
    return normalized


def parse_strict_bool(raw_value: Any) -> bool | None:
    """严格解析布尔值，失败时返回 ``None``。"""
    normalized = _normalize_bool_candidate(raw_value)
    if isinstance(normalized, bool):
        return normalized
    if normalized is None:
        return None
    if normalized in _TRUE_BOOL_TEXTS:
        return True
    if normalized in _FALSE_BOOL_TEXTS:
        return False
    return None


def _normalize_bool_candidate(raw_value: Any) -> str | bool | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, int):
        if raw_value in {0, 1}:
            return bool(raw_value)
        return None
    if isinstance(raw_value, bytes | bytearray):
        try:
            raw_value = raw_value.decode()
        except UnicodeDecodeError:
            return None
    if not isinstance(raw_value, str):
        return None
    return raw_value.strip().lower()


def parse_required_int(raw_value: Any, *, field_name: str) -> int:
    """严格解析整数，失败时抛 ``ValueError``。"""
    parsed = parse_strict_int(raw_value)
    if parsed is None:
        raise ValueError(f"{field_name} must be an integer")
    return parsed
