"""内部服务调用传输层模块。"""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Self, TypeVar
from uuid import uuid4

import httpx

from ...core.api_codes import HttpStatus
from ...core.coercion import parse_strict_int
from ...core.model_normalization import normalize_required_str as _normalize_required_text
from ...observability.logging import get_request_id, normalize_request_id

__all__ = [
    "InternalAPICall",
    "ServiceClientError",
    "ServiceHttpClient",
    "resolve_internal_service_base_url",
]

T = TypeVar("T")

# 默认仅对无副作用的只读请求重试；写请求需由调用方按幂等语义显式开启。
_DEFAULT_RETRY_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})
_DEFAULT_RETRY_STATUS_CODES: frozenset[int] = frozenset(
    {
        HttpStatus.TOO_MANY_REQUESTS,
        HttpStatus.BAD_GATEWAY,
        HttpStatus.SERVICE_UNAVAILABLE,
        HttpStatus.GATEWAY_TIMEOUT,
    }
)
_PROTECTED_FORWARD_HEADERS: frozenset[str] = frozenset({"x-request-id", "authorization"})
_SERVER_ERROR_MESSAGE = "服务调用异常"
_HTTP_SERVER_ERROR_MIN = 500
_HTTP_SERVER_ERROR_MAX = 599
_BUSINESS_SERVER_ERROR_MIN = 50_000
_BUSINESS_SERVER_ERROR_MAX = 59_999


def _parse_number(value: Any, *, field_name: str) -> float:
    """解析数值参数并保留统一错误文案。"""
    if isinstance(value, bool):
        raise ValueError(f"{field_name} 必须为数字")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} 必须为数字") from exc


class ServiceClientError(Exception):
    """跨服务 HTTP 调用异常。"""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def resolve_internal_service_base_url(
    *,
    explicit_base_url: str | None,
    env_var: str,
) -> str:
    """解析并校验内部服务 base_url。"""
    resolved = (explicit_base_url or os.getenv(env_var) or "").strip()
    if not resolved:
        raise ValueError(f"内部服务客户端必须配置 {env_var}")
    return resolved.rstrip("/")


class ServiceHttpClient:
    """基础 HTTP 客户端，统一请求配置与错误处理。"""

    def __init__(
        self,
        base_url: str,
        *,
        api_token: str | None = None,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_attempts: int = 3,
        retry_backoff: float = 0.5,
        retry_methods: Iterable[str] | None = None,
    ) -> None:
        normalized_base_url = _normalize_required_text(base_url, field_name="base_url").rstrip("/")
        normalized_api_token = (
            _normalize_required_text(api_token, field_name="api_token")
            if api_token is not None
            else None
        )
        resolved_timeout = _parse_number(timeout, field_name="timeout")
        resolved_retry_backoff = _parse_number(retry_backoff, field_name="retry_backoff")
        resolved_retry_attempts = parse_strict_int(retry_attempts)
        if resolved_retry_attempts is None:
            raise ValueError("retry_attempts 必须为整数")
        if resolved_timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        if resolved_retry_attempts < 1:
            raise ValueError("retry_attempts 必须大于等于 1")
        if resolved_retry_backoff < 0:
            raise ValueError("retry_backoff 必须大于等于 0")

        self._base_url = normalized_base_url
        self._api_token = normalized_api_token
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=resolved_timeout,
            transport=transport,
        )
        self._retry_attempts = resolved_retry_attempts
        self._retry_backoff = resolved_retry_backoff
        self._retry_status_codes = _DEFAULT_RETRY_STATUS_CODES
        self._retry_methods = self._resolve_retry_methods(retry_methods)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: list[tuple[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
        expected_code: int = 200,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """发送请求并返回解析后的响应 envelope。"""
        normalized_method = method.strip().upper()
        if not normalized_method:
            raise ValueError("请求方法不能为空")
        url = self._normalize_path(path)
        last_exc: Exception | None = None
        for attempt in range(1, self._retry_attempts + 1):
            try:
                response = await self._send_request_once(
                    method=normalized_method,
                    url=url,
                    params=params,
                    json=json,
                    data=data,
                    files=files,
                    headers=headers,
                    request_id=request_id,
                )
                return self._parse_response(response, expected_code=expected_code)
            except ServiceClientError as exc:
                last_exc = exc
                status = self._extract_status_code(exc)
                if not self._should_retry(
                    status_code=status,
                    attempt=attempt,
                    method=normalized_method,
                ):
                    raise
                await asyncio.sleep(self._calc_backoff(attempt))
            except httpx.RequestError as exc:
                last_exc = self._build_request_error(exc)
                if not self._should_retry(
                    status_code=None,
                    attempt=attempt,
                    method=normalized_method,
                ):
                    raise last_exc from exc
                await asyncio.sleep(self._calc_backoff(attempt))
        if last_exc:
            raise last_exc
        raise ServiceClientError("请求失败：未知错误")

    async def _send_request_once(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, Any] | None,
        json: dict[str, Any] | None,
        data: dict[str, Any] | None,
        files: list[tuple[str, Any]] | None,
        headers: dict[str, str] | None,
        request_id: str | None,
    ) -> httpx.Response:
        return await self._client.request(
            method=method,
            url=url,
            params=params,
            json=json,
            data=data,
            files=files,
            headers=self._build_headers(request_id=request_id, extra=headers),
        )

    @staticmethod
    def _build_request_error(exc: httpx.RequestError) -> ServiceClientError:
        return ServiceClientError("请求失败：网络异常")

    def _build_headers(
        self,
        *,
        request_id: str | None,
        extra: dict[str, str] | None,
    ) -> dict[str, str]:
        explicit_request_id = normalize_request_id(request_id)
        header_request_id = self._extract_request_id_from_headers(extra)
        contextual_request_id = normalize_request_id(get_request_id())
        resolved_request_id = (
            explicit_request_id or header_request_id or contextual_request_id or str(uuid4())
        )

        headers: dict[str, str] = {
            "Accept": "application/json",
            "X-Request-ID": resolved_request_id,
        }
        if extra:
            headers.update(self._without_protected_headers(extra))
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        # 规范化后统一写回，避免被空白或占位 request_id 覆盖。
        headers["X-Request-ID"] = resolved_request_id
        return headers

    @staticmethod
    def _extract_request_id_from_headers(headers: dict[str, str] | None) -> str | None:
        if not headers:
            return None
        for key, value in headers.items():
            if key.lower() == "x-request-id":
                return normalize_request_id(value)
        return None

    @staticmethod
    def _without_protected_headers(headers: Mapping[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, value in headers.items():
            if key.lower() in _PROTECTED_FORWARD_HEADERS:
                continue
            normalized[key] = value
        return normalized

    def _parse_response(self, response: httpx.Response, *, expected_code: int) -> dict[str, Any]:
        if response.status_code >= 400:
            raise self._build_http_error(response)
        envelope = self._parse_response_json(response)
        self._validate_expected_code(
            envelope,
            response_status=response.status_code,
            expected_code=expected_code,
        )
        return envelope

    @staticmethod
    def _build_http_error(response: httpx.Response) -> ServiceClientError:
        base_message = f"请求失败：HTTP {response.status_code}"
        message = ServiceHttpClient._merge_http_error_message(base_message, response)
        response_request_id = ServiceHttpClient._normalize_response_request_id(response)
        if response_request_id:
            message = f"{message} (request_id={response_request_id})"
        return ServiceClientError(message, status_code=response.status_code)

    @staticmethod
    def _merge_http_error_message(base_message: str, response: httpx.Response) -> str:
        if response.status_code >= 500:
            return base_message

        try:
            payload = response.json()
        except ValueError:
            return base_message
        if not isinstance(payload, dict):
            return base_message

        raw_message = payload.get("message")
        if not isinstance(raw_message, str):
            return base_message
        normalized_message = raw_message.strip()
        if not normalized_message:
            return base_message

        raw_code = payload.get("code")
        parsed_code = parse_strict_int(raw_code)
        if parsed_code is None:
            return f"{base_message}, message={normalized_message}"
        return f"{base_message}, code={parsed_code}, message={normalized_message}"

    @staticmethod
    def _normalize_response_request_id(response: httpx.Response) -> str | None:
        request_id = response.headers.get("x-request-id")
        return normalize_request_id(request_id)

    @staticmethod
    def _parse_response_json(response: httpx.Response) -> dict[str, Any]:
        try:
            envelope = response.json()
        except ValueError as exc:
            raise ServiceClientError("响应不是合法 JSON", status_code=response.status_code) from exc
        if not isinstance(envelope, dict):
            raise ServiceClientError("响应 JSON 结构非法", status_code=response.status_code)
        return envelope

    @staticmethod
    def _validate_expected_code(
        envelope: dict[str, Any],
        *,
        response_status: int,
        expected_code: int,
    ) -> None:
        raw_code = envelope.get("code")
        if raw_code is None:
            raise ServiceClientError("响应缺少 code 字段", status_code=response_status)
        code = ServiceHttpClient._parse_response_code(
            raw_code,
            response_status=response_status,
        )
        if code != expected_code:
            message = ServiceHttpClient._resolve_business_error_message(envelope, code=code)
            raise ServiceClientError(message, status_code=response_status)

    @staticmethod
    def _parse_response_code(raw_code: Any, *, response_status: int) -> int:
        parsed_code = parse_strict_int(raw_code)
        if parsed_code is not None:
            return parsed_code
        raise ServiceClientError("响应 code 字段非法", status_code=response_status)

    @staticmethod
    def _is_server_error_code(code: int) -> bool:
        return (
            _HTTP_SERVER_ERROR_MIN <= code <= _HTTP_SERVER_ERROR_MAX
            or _BUSINESS_SERVER_ERROR_MIN <= code <= _BUSINESS_SERVER_ERROR_MAX
        )

    @staticmethod
    def _resolve_business_error_message(envelope: Mapping[str, Any], *, code: int) -> str:
        if ServiceHttpClient._is_server_error_code(code):
            return _SERVER_ERROR_MESSAGE
        raw_message = envelope.get("message")
        if not isinstance(raw_message, str):
            return _SERVER_ERROR_MESSAGE
        return raw_message.strip() or _SERVER_ERROR_MESSAGE

    @staticmethod
    def _normalize_path(path: str) -> str:
        if not isinstance(path, str):
            raise ValueError("path 必须为字符串")
        normalized = path.strip()
        if not normalized:
            raise ValueError("path 不能为空")
        return "/" + normalized.lstrip("/")

    @staticmethod
    def _resolve_retry_methods(value: Iterable[str] | None) -> frozenset[str]:
        if value is None:
            return _DEFAULT_RETRY_METHODS
        if isinstance(value, str):
            raise ValueError("retry_methods 必须包含 HTTP 方法字符串")

        normalized: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                raise ValueError("retry_methods 必须包含 HTTP 方法字符串")
            method = item.strip().upper()
            if not method:
                raise ValueError("retry_methods 不能包含空方法名")
            normalized.add(method)
        return frozenset(normalized)

    def _should_retry(self, *, status_code: int | None, attempt: int, method: str) -> bool:
        if attempt >= self._retry_attempts:
            return False
        if method not in self._retry_methods:
            return False
        if status_code is None:
            return True
        return status_code in self._retry_status_codes

    @staticmethod
    def _extract_status_code(exc: Exception) -> int | None:
        if isinstance(exc, ServiceClientError):
            return exc.status_code
        return None

    def _calc_backoff(self, attempt: int) -> float:
        # Full jitter：避免多实例在同一时刻同频重试造成脉冲流量。
        ceiling = self._retry_backoff * (2 ** (attempt - 1))
        if ceiling <= 0:
            return 0.0
        # 使用 secrets 采样，避免普通 PRNG 被 bandit 标记。
        scale = 1_000_000
        ratio = secrets.randbelow(scale + 1) / scale
        return ratio * ceiling


@dataclass(slots=True)
class InternalAPICall(Generic[T]):
    """内部服务调用的请求描述，便于复用模板。"""

    method: str
    path: str
    params: dict[str, Any] | None = None
    json: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    files: list[tuple[str, Any]] | None = None
    expected_code: int = 200
    parser: Callable[[dict[str, Any] | None], T] | None = None
