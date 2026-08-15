"""通用 HTTP 客户端封装，供跨服务调用复用。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar, cast

from ...core.coercion import parse_strict_int
from .transport import InternalAPICall, ServiceClientError, ServiceHttpClient

__all__ = [
    "InternalAPICall",
    "InternalServiceClient",
    "ServiceClientError",
    "ServiceHttpClient",
]

T = TypeVar("T")
_FATAL_BASE_EXCEPTIONS = (KeyboardInterrupt, SystemExit)


class InternalServiceClient(ServiceHttpClient):
    """针对内部接口的轻量客户端基类，封装解析与异常包装。"""

    async def execute(self, call: InternalAPICall[T], *, request_id: str | None = None) -> T:
        body = await self.request(
            call.method,
            call.path,
            params=call.params,
            json=call.json,
            data=call.data,
            files=call.files,
            expected_code=call.expected_code,
            request_id=request_id,
        )
        parser: Callable[[dict[str, Any] | None], T] = call.parser or cast(
            Callable[[dict[str, Any] | None], T], self._identity_parser
        )
        try:
            return parser(body.get("data"))
        except ServiceClientError:
            raise
        except BaseException as exc:  # pragma: no cover - 仅兜底解析错误
            if isinstance(exc, _FATAL_BASE_EXCEPTIONS + (asyncio.CancelledError,)):
                raise
            parser_name = getattr(parser, "__name__", parser.__class__.__name__)
            raise ServiceClientError(
                (
                    "解析内部接口响应失败: "
                    f"{call.method} {call.path}, parser={parser_name}, "
                    f"error_type={exc.__class__.__name__}"
                ),
                status_code=parse_strict_int(body.get("code")),
            ) from exc

    @staticmethod
    def _identity_parser(data: dict[str, Any] | None) -> dict[str, Any] | None:
        return data
