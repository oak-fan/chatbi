"""内部用户展示信息 HTTP 客户端。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ....core.collections import deduplicate_preserving_order
from ...core import InternalAPICall, ServiceClientError
from ._base import MainApiInternalClient
from .errors import UserClientError

__all__ = ["UserClient", "UserClientError", "UserDisplay"]


@dataclass(slots=True)
class UserDisplay:
    """用户最小展示信息。"""

    id: int
    username: str
    full_name: str | None
    display_name: str


class UserClient(MainApiInternalClient):
    """封装调用 `main_api` 内部用户展示接口的逻辑。"""

    async def get_display_by_ids(
        self,
        user_ids: list[int],
        *,
        request_id: str | None = None,
    ) -> dict[int, UserDisplay]:
        """按用户 ID 批量查询展示信息。"""

        normalized_user_ids = _normalize_user_ids(user_ids)
        if not normalized_user_ids:
            return {}
        call = InternalAPICall(
            method="POST",
            path="/internal/v1/users/display",
            json={"user_ids": normalized_user_ids},
            parser=_parse_user_display_map,
        )
        try:
            return await self.execute(call, request_id=request_id)
        except ServiceClientError as exc:
            raise UserClientError(
                f"获取用户展示信息失败：{exc.message}",
                status_code=exc.status_code,
            ) from exc


def _normalize_user_ids(values: Any) -> list[int]:
    if not isinstance(values, list):
        raise UserClientError("user_ids 必须为正整数列表")
    normalized = deduplicate_preserving_order(_normalize_user_id(value) for value in values)
    return list(normalized)


def _normalize_user_id(value: Any) -> int:
    if value is None:
        raise UserClientError("user_ids 必须为正整数列表")
    if isinstance(value, bool):
        raise UserClientError("user_ids 必须为正整数列表")
    try:
        user_id = int(value)
    except (TypeError, ValueError) as exc:
        raise UserClientError("user_ids 必须为正整数列表") from exc
    if user_id <= 0:
        raise UserClientError("user_ids 必须为正整数列表")
    return user_id


def _parse_user_display_map(data: dict[str, Any] | None) -> dict[int, UserDisplay]:
    if data is None:
        raise UserClientError("响应中的用户展示数据格式非法")
    if not isinstance(data, dict):
        raise UserClientError("响应中的用户展示数据格式非法")
    items = data.get("items")
    if not isinstance(items, list):
        raise UserClientError("响应中的用户展示数据格式非法")
    records = [_parse_user_display(item) for item in items]
    return {record.id: record for record in records}


def _parse_user_display(item: Any) -> UserDisplay:
    if not isinstance(item, dict):
        raise UserClientError("响应中的用户展示数据格式非法")
    user_id = _parse_positive_int(item.get("id"), field_name="id")
    username = _parse_required_text(item.get("username"), field_name="username")
    full_name = _parse_optional_text(item.get("full_name"), field_name="full_name")
    display_name = _parse_required_text(item.get("display_name"), field_name="display_name")
    return UserDisplay(
        id=user_id,
        username=username,
        full_name=full_name,
        display_name=display_name,
    )


def _parse_positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool):
        raise UserClientError(f"响应中的 {field_name} 格式非法")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise UserClientError(f"响应中的 {field_name} 格式非法") from exc
    if parsed <= 0:
        raise UserClientError(f"响应中的 {field_name} 格式非法")
    return parsed


def _parse_required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise UserClientError(f"响应中的 {field_name} 格式非法")
    normalized = value.strip()
    if not normalized:
        raise UserClientError(f"响应中的 {field_name} 不能为空")
    return normalized


def _parse_optional_text(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise UserClientError(f"响应中的 {field_name} 格式非法")
    normalized = value.strip()
    return normalized or None
