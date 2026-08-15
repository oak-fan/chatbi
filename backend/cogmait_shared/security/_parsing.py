"""Security 模块内部解析工具。"""

from __future__ import annotations

from ..core.coercion import parse_strict_int


def try_parse_strict_int(value: object) -> int | None:
    """仅接受严格整型输入，拒绝 bool/float/空白。"""
    return parse_strict_int(value)
