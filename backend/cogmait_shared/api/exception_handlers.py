"""通用 FastAPI 全局异常处理，统一响应格式。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..core.api_codes import HttpStatus
from ..observability.logging import logger
from .response import ResponseEnvelope, ResponseFactory

_ERROR_RESPONSE_FACTORY = ResponseFactory(include_request_id=True, as_dict=False)


def _build_error_envelope(
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> ResponseEnvelope:
    """构造错误包裹，默认附带 request_id。"""
    return cast(
        ResponseEnvelope,
        _ERROR_RESPONSE_FACTORY.error(code=code, message=message, data=data),
    )


def _resolve_http_exception_message(detail: Any) -> str:
    fallback_message = "请求处理失败"
    if isinstance(detail, str):
        return detail.strip() or fallback_message
    return fallback_message


def _is_response_envelope_detail(detail: Any) -> bool:
    if not isinstance(detail, dict) or "code" not in detail:
        return False
    message = detail.get("message")
    return isinstance(message, str) and bool(message.strip())


def _sanitize_validation_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """脱敏 Pydantic 校验错误，避免将原始入参回显到响应体。"""
    sanitized: list[dict[str, Any]] = []
    for item in errors:
        if not isinstance(item, dict):
            continue
        payload: dict[str, Any] = {}
        location = item.get("loc")
        if isinstance(location, list | tuple):
            payload["loc"] = [part for part in location if isinstance(part, str | int)]
        message = item.get("msg")
        if isinstance(message, str):
            payload["msg"] = message
        error_type = item.get("type")
        if isinstance(error_type, str):
            payload["type"] = error_type
        if payload:
            sanitized.append(payload)
    return sanitized


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """统一包装 HTTPException 的返回结构。"""
    del request
    envelope: ResponseEnvelope
    http_exc = cast(HTTPException, exc)
    detail = http_exc.detail

    if isinstance(detail, ResponseEnvelope):
        envelope = detail
    elif _is_response_envelope_detail(detail):
        detail_payload = cast(dict[str, Any], detail)
        try:
            envelope = ResponseEnvelope.model_validate(detail_payload)
        except ValidationError:
            envelope = _build_error_envelope(
                code=http_exc.status_code,
                message=_resolve_http_exception_message(detail_payload.get("message")),
            )
    else:
        envelope = _build_error_envelope(
            code=http_exc.status_code,
            message=_resolve_http_exception_message(detail),
        )
    return JSONResponse(
        status_code=http_exc.status_code,
        content=envelope.to_dict(),
        headers=http_exc.headers,
    )


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """422 校验错误统一包装。"""
    del request
    validation_exc = cast(RequestValidationError, exc)
    envelope = _build_error_envelope(
        code=HttpStatus.UNPROCESSABLE_ENTITY,
        message="请求参数校验失败",
        data={"errors": _sanitize_validation_errors(validation_exc.errors())},
    )
    return JSONResponse(
        status_code=HttpStatus.UNPROCESSABLE_ENTITY,
        content=envelope.to_dict(),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底未捕获异常，返回统一错误响应。"""
    del request
    logger.error("Unhandled exception: error_type={}", exc.__class__.__name__)
    envelope = _build_error_envelope(
        code=HttpStatus.INTERNAL_ERROR,
        message="内部服务器错误",
    )
    return JSONResponse(
        status_code=HttpStatus.INTERNAL_ERROR,
        content=envelope.to_dict(),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI 应用上注册全局异常处理。"""
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


__all__ = ["register_exception_handlers"]
