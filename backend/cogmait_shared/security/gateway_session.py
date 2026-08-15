"""Gateway 会话头契约与最小会话构建。

共享层只负责解析可信网关透传的上下文，并恢复最小 `SessionContext`。
具体权限常量、角色来源、菜单模型和权限装配由各服务自行维护。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cogmait_shared.core.types import SnowflakeID

from .account import AccountType
from .gateway_context import (
    ACCOUNT_TYPE_HEADER,
    CLIENT_META_HEADER,
    GATEWAY_TOKEN_HEADER,
    SESSION_ID_HEADER,
    USER_ID_HEADER,
    USERNAME_HEADER,
)
from .session import SessionContext


class GatewaySessionHeaders(BaseModel):
    """网关透传的会话请求头。"""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    gateway_token: str | None = Field(default=None, alias=GATEWAY_TOKEN_HEADER)
    user_id: SnowflakeID | None = Field(default=None, alias=USER_ID_HEADER)
    username: str | None = Field(default=None, alias=USERNAME_HEADER)
    account_type: str | None = Field(default=None, alias=ACCOUNT_TYPE_HEADER)
    session_id: str | None = Field(default=None, alias=SESSION_ID_HEADER)
    client_meta: str | None = Field(default=None, alias=CLIENT_META_HEADER)


def parse_gateway_session_headers(headers: dict[str, Any]) -> GatewaySessionHeaders:
    """解析并校验网关透传头。"""

    try:
        return GatewaySessionHeaders.model_validate(headers)
    except ValidationError as exc:
        raise ValueError("用户上下文无效") from exc


def build_gateway_session_context(headers: GatewaySessionHeaders) -> SessionContext:
    """将网关头声明转换为最小会话上下文。"""

    username = (headers.username or "").strip()
    if headers.user_id is None or not username:
        raise ValueError("缺少用户上下文")

    account_type = AccountType.normalize(headers.account_type)
    if headers.account_type is None:
        raise ValueError("缺少账号类型")
    if account_type is None:
        raise ValueError("账号类型无效")

    return SessionContext(
        session_id=resolve_gateway_session_id(headers.session_id),
        user_id=headers.user_id,
        username=username,
        account_type=account_type,
        roles=[],
        permissions=[],
        is_super_admin=AccountType.is_super_admin(account_type),
        client_meta=_parse_client_meta(headers.client_meta),
        expires_at=None,
    )


def resolve_gateway_session_id(raw_session_id: str | None) -> str:
    """解析会话 ID。"""

    session_id = (raw_session_id or "").strip()
    if session_id:
        return session_id
    raise ValueError("缺少会话上下文")


def _parse_client_meta(raw_client_meta: str | None) -> dict[str, Any] | None:
    if raw_client_meta is None:
        return None

    text = raw_client_meta.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("客户端信息无效") from exc

    if not isinstance(parsed, dict):
        raise ValueError("客户端信息无效")
    return parsed


__all__ = [
    "GatewaySessionHeaders",
    "build_gateway_session_context",
    "parse_gateway_session_headers",
    "resolve_gateway_session_id",
]
