"""内部通知服务 HTTP 客户端。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ....core.collections import deduplicate_preserving_order
from ....core.types import SnowflakeID
from ....enums import NotificationSourceCode, normalize_notification_source_code
from ...core import (
    InternalAPICall,
    ServiceClientError,
)
from ._base import MainApiInternalClient
from .errors import NotificationClientError

__all__ = ["NotificationClient", "NotificationClientError", "NotificationSendPayload"]


@dataclass(slots=True)
class NotificationSendPayload:
    """内部通知发送载体。"""

    title: str
    content: str
    target_user_ids: list[SnowflakeID]
    source_code: NotificationSourceCode | str
    redirect_url: str | None = None


class NotificationClient(MainApiInternalClient):
    """封装调用 `main_api` `/internal/v1/notifications/send` 接口的逻辑。"""

    async def send_notification(
        self,
        payload: NotificationSendPayload,
        *,
        request_id: str | None = None,
    ) -> int:
        """发送一条内部通知并返回通知 ID。"""
        call = InternalAPICall(
            method="POST",
            path="/internal/v1/notifications/send",
            json=_build_send_payload(payload),
            parser=_parse_notification_id,
        )
        try:
            return await self.execute(call, request_id=request_id)
        except ServiceClientError as exc:
            raise NotificationClientError(
                f"发送通知失败：{exc.message}",
                status_code=exc.status_code,
            ) from exc


def _build_send_payload(payload: NotificationSendPayload) -> dict[str, Any]:
    title = _normalize_required_text(payload.title, field_name="title")
    content = _normalize_required_text(payload.content, field_name="content")
    target_user_ids = _normalize_target_user_ids(payload.target_user_ids)
    source_code = _normalize_source_code(payload.source_code)
    redirect_url = _normalize_redirect_url(payload.redirect_url)
    data: dict[str, Any] = {
        "title": title,
        "content": content,
        "target_user_ids": target_user_ids,
        "source_code": source_code,
    }
    if redirect_url is not None:
        data["redirect_url"] = redirect_url
    return data


def _normalize_required_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise NotificationClientError(f"{field_name} 必须为字符串")
    normalized = value.strip()
    if not normalized:
        raise NotificationClientError(f"{field_name} 不能为空")
    return normalized


def _normalize_target_user_ids(values: Any) -> list[SnowflakeID]:
    if not isinstance(values, list):
        raise NotificationClientError("target_user_ids 必须为整数列表")
    normalized = deduplicate_preserving_order(_normalize_target_user_id(value) for value in values)
    if not normalized:
        raise NotificationClientError("target_user_ids 不能为空")
    return normalized


def _normalize_target_user_id(value: Any) -> SnowflakeID:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise NotificationClientError("target_user_ids 必须为正整数列表")
    return value


def _normalize_source_code(value: Any) -> str:
    try:
        return normalize_notification_source_code(value)
    except ValueError as exc:
        raise NotificationClientError("source_code 取值非法") from exc


def _normalize_redirect_url(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NotificationClientError("redirect_url 必须为字符串")
    normalized = value.strip()
    return normalized or None


def _parse_notification_id(data: dict[str, Any] | None) -> int:
    if not data or "notification_id" not in data:
        raise NotificationClientError("响应缺少 notification_id")
    value = data["notification_id"]
    if isinstance(value, str):
        value = value.strip()
        if not value:
            raise NotificationClientError("响应中的 notification_id 不能为空")
    if isinstance(value, bool):
        raise NotificationClientError("响应中的 notification_id 格式非法")
    try:
        notification_id = int(value)
    except (TypeError, ValueError) as exc:
        raise NotificationClientError("响应中的 notification_id 格式非法") from exc
    if notification_id <= 0:
        raise NotificationClientError("响应中的 notification_id 格式非法")
    return notification_id
