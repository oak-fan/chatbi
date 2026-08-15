"""统一的 API 响应格式封装。

该模块提供了一个简单的响应包裹模型以及便捷工厂函数，用于确保
各服务返回的 JSON 结构保持一致（例如 ``{"code": 200, "message": "success", "data": {...}}``）。
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..core.api_codes import HttpStatus
from ..observability.logging import get_request_id, normalize_request_id

__all__ = [
    "ResponseEnvelope",
    "DEFAULT_SUCCESS_MESSAGE",
    "DEFAULT_ERROR_MESSAGE",
    "success",
    "error",
    "ResponseFactory",
]

DEFAULT_SUCCESS_MESSAGE = "success"
DEFAULT_ERROR_MESSAGE = "error"


class ResponseEnvelope(BaseModel):
    """标准 API 响应包裹结构。"""

    model_config = ConfigDict(populate_by_name=True)

    timestamp: int = Field(
        default_factory=lambda: time.time_ns() // 1_000_000,
        description="响应生成时间的 13 位毫秒级 Unix 时间戳。",
    )
    code: int = Field(
        default=HttpStatus.OK,
        description="业务状态码。默认与 HTTP 200 对齐。",
    )
    message: str = Field(default=DEFAULT_SUCCESS_MESSAGE, description="响应描述信息。")
    data: Any | None = Field(default=None, description="实际返回的数据载荷。")
    request_id: str | None = Field(
        default=None,
        serialization_alias="requestId",
        validation_alias="requestId",
        description="可选：请求关联 ID，用于排查链路问题。",
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为适合 FastAPI/JSONResponse 的字典，并保留稳定的 data 字段。"""
        payload = self.model_dump(by_alias=True, exclude_none=True)
        if "data" not in payload:
            payload["data"] = None
        return payload


def _resolve_request_id(
    explicit: str | None,
    *,
    include_request_id: bool,
) -> str | None:
    explicit_request_id = normalize_request_id(explicit)
    if explicit_request_id:
        return explicit_request_id
    if include_request_id:
        return normalize_request_id(get_request_id())
    return None


def _build_envelope(
    *,
    code: int,
    message: str,
    data: Any | None,
    request_id: str | None,
    include_request_id: bool,
) -> ResponseEnvelope:
    resolved_request_id = _resolve_request_id(request_id, include_request_id=include_request_id)
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
        "data": data,
    }
    if resolved_request_id:
        payload["request_id"] = resolved_request_id
    return ResponseEnvelope.model_validate(payload)


def success(
    data: Any | None = None,
    *,
    code: int = HttpStatus.OK,
    message: str = DEFAULT_SUCCESS_MESSAGE,
    request_id: str | None = None,
    include_request_id: bool = False,
) -> ResponseEnvelope:
    """构造成功响应包裹。"""
    return _build_envelope(
        code=code,
        message=message,
        data=data,
        request_id=request_id,
        include_request_id=include_request_id,
    )


def error(
    *,
    code: int = HttpStatus.INTERNAL_ERROR,
    message: str = DEFAULT_ERROR_MESSAGE,
    data: Any | None = None,
    request_id: str | None = None,
    include_request_id: bool = False,
) -> ResponseEnvelope:
    """构造失败响应包裹，默认业务码与 HTTP 500 对齐。"""
    return _build_envelope(
        code=code,
        message=message,
        data=data,
        request_id=request_id,
        include_request_id=include_request_id,
    )


_success_envelope_builder = success
_error_envelope_builder = error


class ResponseFactory:
    """服务内部统一的响应构造器。

    该工厂复用 shared 层的 `success` / `error`，并允许控制是否默认附带 `request_id`
    以及返回 `dict` 还是 `ResponseEnvelope`，方便在 FastAPI 依赖中统一注入。
    """

    def __init__(
        self,
        *,
        include_request_id: bool = True,
        as_dict: bool = True,
    ) -> None:
        self.default_include_request_id = include_request_id
        self.default_as_dict = as_dict

    def success(
        self,
        data: Any | None = None,
        *,
        code: int = HttpStatus.OK,
        message: str = DEFAULT_SUCCESS_MESSAGE,
        request_id: str | None = None,
        include_request_id: bool | None = None,
        as_dict: bool | None = None,
    ) -> ResponseEnvelope | dict[str, Any]:
        """构造成功响应。"""
        resolved_include = self._resolve_include_request_id(include_request_id)
        envelope = _success_envelope_builder(
            data=data,
            code=code,
            message=message,
            request_id=request_id,
            include_request_id=resolved_include,
        )
        return self._render_envelope(envelope, as_dict=as_dict)

    def error(
        self,
        *,
        code: int = HttpStatus.INTERNAL_ERROR,
        message: str = DEFAULT_ERROR_MESSAGE,
        data: Any | None = None,
        request_id: str | None = None,
        include_request_id: bool | None = None,
        as_dict: bool | None = None,
    ) -> ResponseEnvelope | dict[str, Any]:
        """构造失败响应。"""
        resolved_include = self._resolve_include_request_id(include_request_id)
        envelope = _error_envelope_builder(
            code=code,
            message=message,
            data=data,
            request_id=request_id,
            include_request_id=resolved_include,
        )
        return self._render_envelope(envelope, as_dict=as_dict)

    def _resolve_include_request_id(self, include_request_id: bool | None) -> bool:
        if include_request_id is None:
            return self.default_include_request_id
        return include_request_id

    def _render_envelope(
        self,
        envelope: ResponseEnvelope,
        *,
        as_dict: bool | None,
    ) -> ResponseEnvelope | dict[str, Any]:
        should_as_dict = self.default_as_dict if as_dict is None else as_dict
        if should_as_dict:
            return envelope.to_dict()
        return envelope
