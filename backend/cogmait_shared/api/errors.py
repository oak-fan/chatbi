"""HTTP 错误响应辅助工具。"""

from __future__ import annotations

from typing import NoReturn, Protocol

from fastapi import HTTPException

from .response import ResponseFactory

EXPOSE_ERROR_MESSAGE_HEADER = "x-cogmait-expose-message"


class ServiceErrorProtocol(Protocol):
    """约束 ServiceError 的最小字段集合。"""

    message: str
    status_code: int
    code: int
    expose_message: bool


def raise_service_error(exc: ServiceErrorProtocol, response_factory: ResponseFactory) -> NoReturn:
    """按统一响应结构抛出 HTTPException。"""
    envelope = response_factory.error(code=exc.code, message=exc.message)
    headers = None
    if exc.expose_message:
        headers = {EXPOSE_ERROR_MESSAGE_HEADER: "true"}
    http_exc = HTTPException(status_code=exc.status_code, detail=envelope, headers=headers)
    if isinstance(exc, BaseException):
        raise http_exc from exc
    raise http_exc


__all__ = [
    "EXPOSE_ERROR_MESSAGE_HEADER",
    "raise_service_error",
    "ServiceErrorProtocol",
]
