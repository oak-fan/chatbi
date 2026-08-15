"""网关透传会话与权威缓存会话的共享校验规则。"""

from __future__ import annotations

from cogmait_shared.cache import CacheOps

from .session import SessionContext, get_active_session_from_cache


async def verify_gateway_session_binding(
    *,
    gateway_session: SessionContext,
    access_token: str,
    cache_service: CacheOps,
) -> SessionContext:
    """校验网关头会话与缓存会话/令牌的一致性。"""

    cached_session = await get_active_session_from_cache(cache_service, access_token)
    if cached_session is None:
        raise ValueError("访问令牌无效或已过期")

    _assert_identity_consistent(
        gateway_session=gateway_session,
        cached_session=cached_session,
    )
    return cached_session


def _assert_identity_consistent(
    *,
    gateway_session: SessionContext,
    cached_session: SessionContext,
) -> None:
    if gateway_session.session_id != cached_session.session_id:
        raise ValueError("用户上下文与访问令牌不匹配")
    if gateway_session.user_id != cached_session.user_id:
        raise ValueError("用户上下文与访问令牌不匹配")
    if gateway_session.username != cached_session.username:
        raise ValueError("用户上下文与访问令牌不匹配")
    if gateway_session.account_type != cached_session.account_type:
        raise ValueError("用户上下文与访问令牌不匹配")
    if gateway_session.is_super_admin != cached_session.is_super_admin:
        raise ValueError("用户上下文与访问令牌不匹配")


__all__ = ["verify_gateway_session_binding"]
