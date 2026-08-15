"""跨服务共享的 API 错误辅助函数。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, NoReturn, TypeVar, cast

from pydantic import BaseModel

from ..core.api_codes import ErrorCode, HttpStatus
from ..service_errors import ServiceError, wrap_value_error
from .errors import ServiceErrorProtocol, raise_service_error
from .response import ResponseEnvelope, ResponseFactory

_ResultT = TypeVar("_ResultT")
_ServiceErrorT = TypeVar("_ServiceErrorT", bound=ServiceErrorProtocol)
_ExceptionT = TypeVar("_ExceptionT", bound=Exception)


def raise_unreachable() -> NoReturn:
    raise AssertionError("unreachable")


def build_domain_input(
    factory: Callable[..., _ResultT],
    payload: Mapping[str, Any] | None = None,
    *,
    response_factory: ResponseFactory,
    error_builder: Callable[[str], _ServiceErrorT],
) -> _ResultT:
    """处理领域输入构造错误。"""
    try:
        return factory(**dict(payload or {}))
    except ValueError as exc:
        raise_service_error(error_builder(str(exc)), response_factory)
        raise_unreachable()


def build_bad_request_error(
    message: str,
    *,
    error_factory: Callable[..., _ServiceErrorT],
) -> _ServiceErrorT:
    """构造参数错误。"""
    return error_factory(
        message,
        code=ErrorCode.PARAMS_INVALID,
        status_code=HttpStatus.BAD_REQUEST,
    )


def build_not_found_error(
    message: str,
    *,
    error_factory: Callable[..., _ServiceErrorT],
) -> _ServiceErrorT:
    """构造资源不存在错误。"""
    return error_factory(
        message,
        code=ErrorCode.NOT_FOUND,
        status_code=HttpStatus.NOT_FOUND,
    )


async def run_service_call(
    operation: Any,
    *,
    response_factory: ResponseFactory,
    error_type: type[_ExceptionT],
) -> Any:
    """包装服务异常。"""
    try:
        return await operation
    except error_type as exc:
        raise_service_error(cast(ServiceErrorProtocol, exc), response_factory)
        raise_unreachable()


def success_response(
    response_factory: ResponseFactory,
    *,
    data: Any | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """返回成功响应。"""
    payload: Any
    if isinstance(data, BaseModel):
        payload = cast(BaseModel, data).model_dump(by_alias=True)
    else:
        payload = data
    response = (
        response_factory.success(data=payload)
        if message is None
        else response_factory.success(data=payload, message=message)
    )
    if isinstance(response, ResponseEnvelope):
        return response.to_dict()
    return response


__all__ = [
    "ServiceError",
    "build_bad_request_error",
    "build_not_found_error",
    "build_domain_input",
    "raise_unreachable",
    "run_service_call",
    "success_response",
    "wrap_value_error",
]
