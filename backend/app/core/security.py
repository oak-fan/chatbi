"""cogmait-chatbi 会话依赖（无鉴权）。"""

from __future__ import annotations

from cogmait_shared.security import SessionContext

from .config import settings

_DEFAULT_SESSION = SessionContext(
    session_id="local-chatbi",
    user_id=settings.default_user_id,
    username=settings.default_username,
    account_type="system",
    roles=(),
    permissions=(),
    is_super_admin=True,
)


async def get_default_session() -> SessionContext:
    """返回固定本地会话，跳过网关与权限校验。"""

    return SessionContext(
        session_id=_DEFAULT_SESSION.session_id,
        user_id=settings.default_user_id,
        username=settings.default_username,
        account_type=_DEFAULT_SESSION.account_type,
        roles=_DEFAULT_SESSION.roles,
        permissions=_DEFAULT_SESSION.permissions,
        is_super_admin=_DEFAULT_SESSION.is_super_admin,
    )


__all__ = ["get_default_session"]
