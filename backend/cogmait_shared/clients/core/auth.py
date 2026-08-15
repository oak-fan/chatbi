"""内部服务调用鉴权模块。"""

from __future__ import annotations

import os

__all__ = [
    "resolve_internal_service_token",
]


def resolve_internal_service_token(explicit_token: str | None = None) -> str:
    """解析并校验内部服务调用 token。"""
    resolved = (explicit_token or os.getenv("SERVICE_TOKEN") or "").strip()
    if not resolved:
        raise ValueError("内部服务客户端必须配置 SERVICE_TOKEN")
    if resolved == "change-me-internal":
        raise ValueError("SERVICE_TOKEN 不能使用占位值 'change-me-internal'")
    return resolved
