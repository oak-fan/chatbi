"""仓储层通用工具。"""

from __future__ import annotations


def escape_like(value: str) -> str:
    """转义 LIKE 模式中的通配符字符。"""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = ["escape_like"]
