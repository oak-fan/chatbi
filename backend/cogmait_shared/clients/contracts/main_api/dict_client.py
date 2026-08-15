"""服务间同步字典数据的 HTTP 客户端。"""

from __future__ import annotations

import re
from typing import Any

from ....dicts import DictDefinition
from ...core import (
    InternalAPICall,
    ServiceClientError,
)
from ._base import MainApiInternalClient
from .errors import DictClientError

__all__ = ["DictClient", "DictClientError"]

_PATH_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")


class DictClient(MainApiInternalClient):
    """封装调用 `main_api` 内部字典接口的逻辑。"""

    async def get_dict(
        self,
        dict_type: str,
        *,
        include_disabled: bool = False,
        request_id: str | None = None,
    ) -> DictDefinition | None:
        """拉取指定字典，始终返回最新数据。"""
        normalized_dict_type = _normalize_path_segment(dict_type, field_name="dict_type")
        normalized_include_disabled = _normalize_include_disabled(include_disabled)
        params = {"include_disabled": str(normalized_include_disabled).lower()}
        call = InternalAPICall(
            method="GET",
            path=f"/internal/v1/dicts/{normalized_dict_type}",
            params=params,
            parser=_parse_dict_definition,
        )
        try:
            return await self.execute(call, request_id=request_id)
        except ServiceClientError as exc:
            raise DictClientError(
                f"拉取字典 {normalized_dict_type} 失败：{exc.message}",
                status_code=exc.status_code,
            ) from exc

    async def get_item_code(
        self,
        dict_type: str,
        item_code: str,
        *,
        include_disabled: bool = False,
        request_id: str | None = None,
    ) -> str | None:
        """通过字典编码+字典项编码校验并返回标准 item_code。"""
        normalized_dict_type = _normalize_path_segment(dict_type, field_name="dict_type")
        normalized_item_code = _normalize_path_segment(item_code, field_name="item_code")
        normalized_include_disabled = _normalize_include_disabled(include_disabled)
        params = {"include_disabled": str(normalized_include_disabled).lower()}
        call = InternalAPICall(
            method="GET",
            path=f"/internal/v1/dicts/{normalized_dict_type}/items/{normalized_item_code}/code",
            params=params,
            parser=_parse_item_code,
        )
        try:
            return await self.execute(call, request_id=request_id)
        except ServiceClientError as exc:
            item_key = f"{normalized_dict_type}.{normalized_item_code}"
            message = f"获取字典项 {item_key} 的编码失败：{exc.message}"
            raise DictClientError(
                message,
                status_code=exc.status_code,
            ) from exc


def _parse_dict_definition(data: dict[str, Any] | None) -> DictDefinition | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise DictClientError("响应中的字典数据格式非法")
    try:
        return DictDefinition.from_wire(data)
    except (TypeError, ValueError) as exc:
        raise DictClientError("响应中的字典数据格式非法") from exc


def _parse_item_code(data: Any) -> str | None:
    if data is None:
        return None
    if not isinstance(data, str):
        raise DictClientError("响应中的字典项编码格式非法")
    normalized = data.strip()
    if not normalized:
        raise DictClientError("响应缺少 item_code")
    return normalized


def _normalize_include_disabled(value: Any) -> bool:
    if not isinstance(value, bool):
        raise DictClientError("include_disabled 必须是布尔值")
    return value


def _normalize_path_segment(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise DictClientError(f"{field_name} 必须为字符串")
    normalized = value.strip()
    if not normalized:
        raise DictClientError(f"{field_name} 不能为空")
    if normalized in {".", ".."} or not _PATH_SEGMENT_PATTERN.fullmatch(normalized):
        raise DictClientError(f"{field_name} 包含非法字符")
    return normalized
