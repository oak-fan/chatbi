"""跨服务共享的 FastAPI 安全依赖。"""

from __future__ import annotations

from collections.abc import Callable
from typing import NoReturn

from cogmait_shared.api.response import ResponseFactory
from cogmait_shared.core.api_codes import HttpStatus

from ._fastapi_imports import Header, HTTPException
from .internal_auth import (
    ensure_service_token_configured,
    extract_bearer_token,
    is_token_matched,
    normalize_service_token,
)

ServiceTokenProvider = Callable[[], str | None]


def verify_service_token_value(
    *,
    token: str | None,
    expected_token: str | None,
    response_factory: ResponseFactory | None = None,
    invalid_message: str = "服务令牌无效",
    missing_config_message: str = "服务令牌未配置",
    unauthorized_status_code: int = HttpStatus.UNAUTHORIZED,
    config_error_status_code: int = HttpStatus.INTERNAL_ERROR,
) -> None:
    """校验已提取出的服务令牌值。"""

    expected = normalize_service_token(expected_token)
    _ensure_service_token_configured(
        expected,
        response_factory=response_factory,
        missing_config_message=missing_config_message,
        status_code=config_error_status_code,
    )
    if token is None or not is_token_matched(token=token, expected_token=expected):
        _raise_http_error(
            invalid_message,
            status_code=unauthorized_status_code,
            response_factory=response_factory,
        )


def build_service_token_dependency(
    expected_token_provider: ServiceTokenProvider,
    *,
    response_factory: ResponseFactory | None = None,
    invalid_message: str = "服务令牌无效",
    missing_config_message: str = "服务令牌未配置",
    unauthorized_status_code: int = HttpStatus.UNAUTHORIZED,
    config_error_status_code: int = HttpStatus.INTERNAL_ERROR,
) -> Callable[[str | None], None]:
    """构建基于 Authorization Bearer 的服务令牌校验依赖。"""

    def dependency(authorization: str | None = Header(default=None)) -> None:
        expected = normalize_service_token(expected_token_provider())
        _ensure_service_token_configured(
            expected,
            response_factory=response_factory,
            missing_config_message=missing_config_message,
            status_code=config_error_status_code,
        )

        try:
            token = extract_bearer_token(authorization)
        except ValueError as exc:
            _raise_http_error(
                str(exc),
                status_code=unauthorized_status_code,
                response_factory=response_factory,
            )

        verify_service_token_value(
            token=token,
            expected_token=expected,
            response_factory=response_factory,
            invalid_message=invalid_message,
            missing_config_message=missing_config_message,
            unauthorized_status_code=unauthorized_status_code,
            config_error_status_code=config_error_status_code,
        )

    return dependency


def _ensure_service_token_configured(
    expected_token: str,
    *,
    response_factory: ResponseFactory | None,
    missing_config_message: str,
    status_code: int,
) -> None:
    try:
        ensure_service_token_configured(expected_token)
    except ValueError:
        _raise_http_error(
            missing_config_message,
            status_code=status_code,
            response_factory=response_factory,
        )


def _raise_http_error(
    message: str,
    *,
    status_code: int,
    response_factory: ResponseFactory | None,
) -> NoReturn:
    factory = response_factory or ResponseFactory(include_request_id=True)
    envelope = factory.error(code=status_code, message=message)
    raise HTTPException(status_code=status_code, detail=envelope)


__all__ = ["ServiceTokenProvider", "build_service_token_dependency", "verify_service_token_value"]
