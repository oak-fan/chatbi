"""请求级 request_id 上下文工具。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from uuid import uuid4

_REQUEST_ID_FALLBACK = "-"
REQUEST_ID_CTX: ContextVar[str] = ContextVar(
    "cogmait_request_id",
    default=_REQUEST_ID_FALLBACK,
)


def _normalize_request_id(value: str | None) -> str:
    if value is None:
        return _REQUEST_ID_FALLBACK
    normalized = value.strip()
    if not normalized:
        return _REQUEST_ID_FALLBACK
    return normalized


def normalize_request_id(value: str | None) -> str | None:
    """归一化外部可见的 request_id，过滤空值和占位符。"""
    normalized = _normalize_request_id(value)
    if normalized == _REQUEST_ID_FALLBACK:
        return None
    return normalized


def set_request_id(request_id: str | None) -> Token[str]:
    """在上下文中设置 request_id，返回可用于 reset 的 Token。"""
    return REQUEST_ID_CTX.set(_normalize_request_id(request_id))


def reset_request_id(token: Token[str]) -> None:
    """恢复上下文中的 request_id。"""
    try:
        REQUEST_ID_CTX.reset(token)
    except (ValueError, RuntimeError):
        # token 无效时忽略，避免中间件内异常导致日志不可用
        REQUEST_ID_CTX.set(_REQUEST_ID_FALLBACK)


def get_request_id() -> str:
    """获取当前上下文中的 request_id。"""
    return REQUEST_ID_CTX.get(_REQUEST_ID_FALLBACK)


def ensure_request_id(prefix: str | None = None) -> str:
    """确保当前上下文存在 request_id；若缺失则生成新的 ID 并返回。"""
    current = get_request_id()
    if current and current != _REQUEST_ID_FALLBACK:
        return current

    suffix = uuid4().hex
    new_id = f"{prefix}-{suffix}" if prefix else suffix
    set_request_id(new_id)
    return new_id


@contextmanager
def request_id_context(request_id: str | None) -> Iterator[None]:
    """上下文管理器：在 with 块内设置 request_id，自动清理。"""
    token = set_request_id(request_id)
    try:
        yield
    finally:
        reset_request_id(token)


__all__ = [
    "ensure_request_id",
    "get_request_id",
    "normalize_request_id",
    "request_id_context",
    "reset_request_id",
    "set_request_id",
]
