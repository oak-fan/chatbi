"""安全模块内部共用协议定义。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class PermissionAwareSession(Protocol):
    """提供权限、角色与账号类型信息的最小会话协议。"""

    account_type: str
    permissions: Sequence[str]
    roles: Sequence[str]
    is_super_admin: bool


__all__ = ["PermissionAwareSession"]
