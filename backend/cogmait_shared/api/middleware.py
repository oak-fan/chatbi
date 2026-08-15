"""共享 FastAPI 中间件。"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..observability.logging import request_id_context

__all__ = ["RequestIdMiddleware"]

_REQUEST_ID_MAX_LENGTH = 128


class RequestIdMiddleware:
    """确保请求全链路拥有 request_id 并注入日志上下文。

    - 从请求头读取 `header_name` 指定的字段（默认 `X-Request-ID`）；
    - 若不存在则生成新的 UUID；
    - 将 request_id 写入 `request.state.request_id`、响应头以及日志上下文。
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        header_name: str = "X-Request-ID",
        state_attr: str = "request_id",
        generator: Callable[[], str] | None = None,
    ) -> None:
        self.app = app
        self.header_name = header_name
        self.state_attr = state_attr
        self._header_name_lower = header_name.lower().encode("latin-1")
        self._header_name_bytes = header_name.encode("latin-1")
        self.generator = generator or (lambda: str(uuid.uuid4()))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = self._resolve_request_id(scope)
        state = scope.setdefault("state", {})
        state[self.state_attr] = request_id

        async def send_wrapper(message: Message) -> None:
            if message["type"] != "http.response.start":
                await send(message)
                return

            headers = list(message.get("headers", []))
            has_request_id = any(key.lower() == self._header_name_lower for key, _ in headers)
            if not has_request_id:
                headers.append((self._header_name_bytes, request_id.encode("utf-8")))
                message = {**message, "headers": headers}
            await send(message)

        with request_id_context(request_id):
            await self.app(scope, receive, send_wrapper)

    def _resolve_request_id(self, scope: Scope) -> str:
        incoming_request_id = self._header_value(scope, self._header_name_lower)
        normalized_request_id = incoming_request_id.strip() if incoming_request_id else ""
        if self._is_valid_request_id(normalized_request_id):
            return normalized_request_id
        return self.generator()

    @staticmethod
    def _is_valid_request_id(value: str) -> bool:
        if not value:
            return False
        if len(value) > _REQUEST_ID_MAX_LENGTH:
            return False
        return all(" " <= char <= "~" for char in value)

    @staticmethod
    def _header_value(scope: Scope, header_name: bytes) -> str | None:
        for key, value in scope.get("headers", []):
            if key.lower() != header_name:
                continue
            return value.decode("latin-1")
        return None
