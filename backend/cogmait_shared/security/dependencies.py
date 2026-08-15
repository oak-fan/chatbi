"""FastAPI 依赖工厂，统一会话权限/角色校验。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import NoReturn

from ..api.response import ResponseFactory
from ..core.api_codes import HttpStatus
from ..core.collections import deduplicate_preserving_order
from ._fastapi_imports import Depends, HTTPException
from .account import AccountType
from .protocols import PermissionAwareSession

SessionDependency = Callable[..., Awaitable["PermissionAwareSession"]]
_FORBIDDEN_RESPONSE_FACTORY = ResponseFactory(include_request_id=True, as_dict=True)


def require_permissions(
    *permissions: str,
    session_dependency: SessionDependency,
) -> Callable[..., Awaitable[PermissionAwareSession]]:
    """要求具备提供的全部权限点；超级管理员默认放行。"""

    required = _normalize_required_values(permissions, field_name="permissions")

    async def dependency(
        session: PermissionAwareSession = Depends(session_dependency),
    ) -> PermissionAwareSession:
        if not required or getattr(session, "is_super_admin", False):
            return session
        owned = _normalize_owned_values(getattr(session, "permissions", []))
        missing = [permission for permission in required if permission not in owned]
        if missing:
            joined = ", ".join(missing)
            _raise_forbidden(f"缺少权限: {joined}")
        return session

    return dependency


def require_roles(
    *roles: str,
    session_dependency: SessionDependency,
) -> Callable[..., Awaitable[PermissionAwareSession]]:
    """要求至少命中其中一个角色；超级管理员默认放行。"""

    required = _normalize_required_values(roles, field_name="roles")

    async def dependency(
        session: PermissionAwareSession = Depends(session_dependency),
    ) -> PermissionAwareSession:
        if not required or getattr(session, "is_super_admin", False):
            return session
        owned = _normalize_owned_values(getattr(session, "roles", []))
        if owned.intersection(required):
            return session
        joined = ", ".join(required)
        _raise_forbidden(f"缺少角色: {joined}")
        return session

    return dependency


def require_account_types(
    *account_types: str | AccountType,
    session_dependency: SessionDependency,
) -> Callable[..., Awaitable[PermissionAwareSession]]:
    """要求账户类型命中提供的列表；超级管理员默认放行。"""

    normalized = _normalize_account_types(account_types)

    async def dependency(
        session: PermissionAwareSession = Depends(session_dependency),
    ) -> PermissionAwareSession:
        if not normalized or getattr(session, "is_super_admin", False):
            return session
        current = _normalize_session_account_type(getattr(session, "account_type", None))
        if current is not None and current in normalized:
            return session
        joined = ", ".join(normalized)
        _raise_forbidden(f"账号类型不允许: {joined}")
        return session

    return dependency


def _normalize_required_values(values: Iterable[object], *, field_name: str) -> list[str]:
    return deduplicate_preserving_order(
        _normalize_required_value(value, field_name=field_name) for value in values
    )


def _normalize_required_value(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 只能包含字符串值")
    trimmed = value.strip()
    if not trimmed:
        raise ValueError(f"{field_name} 不能包含空白值")
    return trimmed


def _normalize_owned_values(values: object) -> set[str]:
    normalized: set[str] = set()
    if isinstance(values, str | bytes | bytearray) or not isinstance(values, Iterable):
        return normalized
    for value in values:
        if not isinstance(value, str):
            continue
        trimmed = value.strip()
        if trimmed:
            normalized.add(trimmed)
    return normalized


def _normalize_account_types(account_types: Iterable[str | AccountType]) -> list[str]:
    return deduplicate_preserving_order(
        _parse_account_type(value, field_name="account_types") for value in account_types
    )


def _normalize_session_account_type(value: object) -> str | None:
    return AccountType.normalize(value)


def _parse_account_type(value: object, *, field_name: str) -> str:
    parsed = AccountType.normalize(value)
    if parsed is None:
        raise ValueError(f"{field_name} 只能包含 AccountType 枚举值")
    return parsed


def _raise_forbidden(message: str) -> NoReturn:
    envelope = _FORBIDDEN_RESPONSE_FACTORY.error(
        code=HttpStatus.FORBIDDEN,
        message=message,
    )
    raise HTTPException(status_code=HttpStatus.FORBIDDEN, detail=envelope)


__all__ = [
    "PermissionAwareSession",
    "require_permissions",
    "require_roles",
    "require_account_types",
]
