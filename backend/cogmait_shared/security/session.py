"""会话上下文模型与缓存读取工具。"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..cache import CacheOps
from ..core.datetime_utils import ensure_timezone, now_local, parse_datetime
from ._parsing import try_parse_strict_int
from .account import AccountType
from .protocols import PermissionAwareSession

_SESSION_PREFIX = "auth:session"
_SESSION_CUTOFF_PREFIX = "auth:session-cutoff"
_SESSION_HASH_PREFIX = "sha256:"


@dataclass(slots=True)
class SessionContext(PermissionAwareSession):
    """Redis 中存储的会话上下文。"""

    session_id: str
    user_id: int
    username: str
    account_type: str
    roles: Sequence[str]
    permissions: Sequence[str]
    is_super_admin: bool
    full_name: str | None = None
    client_meta: dict[str, Any] | None = None
    issued_at: datetime | None = None
    expires_at: datetime | None = None


async def get_session_from_cache(cache: CacheOps, access_token: str) -> SessionContext | None:
    """从共享缓存中读取会话上下文。"""

    for key in session_cache_keys(access_token):
        session = await get_session_from_cache_key(cache, key)
        if session is not None:
            return session
    return None


async def get_session_from_cache_key(cache: CacheOps, cache_key: str) -> SessionContext | None:
    """按 access session 缓存 Key 读取会话上下文。"""

    payload = await cache.get_json(cache_key)
    if not isinstance(payload, dict):
        return None
    return _build_session_context(payload)


async def get_active_session_from_cache(
    cache: CacheOps,
    access_token: str,
) -> SessionContext | None:
    """从共享缓存中读取仍然有效的会话上下文。"""

    session = await get_session_from_cache(cache, access_token)
    return await _filter_active_session(cache, session)


async def get_active_session_from_cache_key(
    cache: CacheOps,
    cache_key: str,
) -> SessionContext | None:
    """按 access session 缓存 Key 读取仍然有效的会话上下文。"""

    session = await get_session_from_cache_key(cache, cache_key)
    return await _filter_active_session(cache, session)


async def _filter_active_session(
    cache: CacheOps,
    session: SessionContext | None,
) -> SessionContext | None:
    if session is None:
        return None
    if _is_session_expired(session.expires_at):
        return None
    cutoff = await get_user_session_cutoff(cache, session.user_id)
    if is_session_revoked_by_cutoff(issued_at=session.issued_at, cutoff=cutoff):
        return None
    return session


def _is_session_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return True
    return ensure_timezone(expires_at) <= now_local()


async def get_user_session_cutoff(cache: CacheOps, user_id: int) -> datetime | None:
    """读取用户会话失效截止时间。"""

    raw_value = await cache.get_value(user_session_cutoff_key(user_id))
    return parse_datetime(raw_value)


def is_session_revoked_by_cutoff(
    *,
    issued_at: datetime | None,
    cutoff: datetime | None,
) -> bool:
    """判断会话签发时间是否已被用户级 cutoff 撤销。"""

    if cutoff is None:
        return False
    if issued_at is None:
        return True
    return ensure_timezone(issued_at) <= ensure_timezone(cutoff)


def session_cache_key(access_token: str) -> str:
    """构建 access token 在缓存中的 Key。"""

    return f"{_SESSION_PREFIX}:{_SESSION_HASH_PREFIX}{_hash_access_token(access_token)}"


def session_cache_keys(access_token: str) -> tuple[str, str]:
    """返回当前 Key 与旧版明文 Key，用于平滑迁移。"""

    return session_cache_key(access_token), _legacy_session_cache_key(access_token)


def user_session_cutoff_key(user_id: int) -> str:
    """构建用户会话失效截止时间缓存 Key。"""

    return f"{_SESSION_CUTOFF_PREFIX}:{user_id}"


def _hash_access_token(access_token: str) -> str:
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()


def _legacy_session_cache_key(access_token: str) -> str:
    return f"{_SESSION_PREFIX}:{access_token}"


def _build_session_context(data: dict[str, Any]) -> SessionContext | None:
    session_id = _normalize_required_text(data.get("session_id"))
    user_id = data.get("user_id")
    username = _normalize_required_text(data.get("username"))
    account_type = data.get("account_type")
    if not session_id or user_id is None or not username:
        return None
    if account_type is None:
        return None  # 缺少账户类型视为无效会话，要求重新登录
    resolved_user_id = try_parse_strict_int(user_id)
    resolved_account_type = _require_account_type(account_type)
    resolved_is_super_admin = _require_bool(data.get("is_super_admin"))
    if resolved_user_id is None or resolved_account_type is None or resolved_is_super_admin is None:
        return None
    client_meta = data.get("client_meta")
    meta = client_meta if isinstance(client_meta, dict) else None
    issued_at = parse_datetime(data.get("issued_at"))
    expires_at = parse_datetime(data.get("expires_at"))
    roles = _normalize_string_sequence(data.get("roles"))
    permissions = _normalize_string_sequence(data.get("permissions"))
    if roles is None or permissions is None:
        return None
    return SessionContext(
        session_id=session_id,
        user_id=resolved_user_id,
        username=username,
        full_name=_normalize_optional_text(data.get("full_name")),
        account_type=resolved_account_type,
        roles=roles,
        permissions=permissions,
        is_super_admin=resolved_is_super_admin,
        client_meta=meta,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def _normalize_string_sequence(value: Any) -> list[str] | None:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return None
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        if item != item.strip() or not item:
            return None
        normalized.append(item)
    return normalized


def _require_account_type(value: Any) -> str | None:
    if isinstance(value, AccountType):
        return value.value
    if not isinstance(value, str):
        return None
    return value if value in AccountType._value2member_map_ else None


def _normalize_required_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _normalize_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _require_bool(value: Any) -> bool | None:
    if not isinstance(value, bool):
        return None
    return value


__all__ = [
    "SessionContext",
    "get_active_session_from_cache_key",
    "get_active_session_from_cache",
    "get_session_from_cache_key",
    "get_session_from_cache",
    "get_user_session_cutoff",
    "is_session_revoked_by_cutoff",
    "session_cache_key",
    "session_cache_keys",
    "user_session_cutoff_key",
]
