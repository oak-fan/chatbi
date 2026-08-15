"""内部系统参数 HTTP 客户端。"""

from __future__ import annotations

import re
from typing import Any

from ...core import (
    InternalAPICall,
    ServiceClientError,
)
from ._base import MainApiInternalClient
from .errors import ConfigClientError

__all__ = ["ConfigClient", "ConfigClientError"]

_CONFIG_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")


class ConfigClient(MainApiInternalClient):
    """封装调用 `main_api` `/internal/v1/configs` 接口的逻辑。"""

    async def get_value(self, config_key: str, *, request_id: str | None = None) -> str | None:
        """按配置键获取系统参数值。"""
        normalized_key = _normalize_config_key(config_key)
        call = InternalAPICall(
            method="GET",
            path=f"/internal/v1/configs/{normalized_key}",
            parser=_parse_config_value,
        )
        try:
            return await self.execute(call, request_id=request_id)
        except ServiceClientError as exc:
            raise ConfigClientError(
                f"获取系统参数 {normalized_key} 失败：{exc.message}",
                status_code=exc.status_code,
            ) from exc


def _normalize_config_key(config_key: Any) -> str:
    if not isinstance(config_key, str):
        raise ConfigClientError("config_key 必须为字符串")
    normalized = config_key.strip()
    if not normalized:
        raise ConfigClientError("config_key 不能为空")
    if _CONFIG_KEY_PATTERN.fullmatch(normalized) is None:
        raise ConfigClientError("config_key 只能包含字母、数字、下划线、点、冒号和短横线")
    return normalized


def _parse_config_value(data: Any) -> str | None:
    if data is None:
        return None
    if not isinstance(data, str):
        raise ConfigClientError("响应中的参数值格式非法")
    return data
