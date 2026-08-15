"""跨服务共享的安全骨架。

共享层只提供会话契约、网关上下文契约、通用校验依赖和服务间 token 校验。
具体权限常量、权限来源与业务模型装配由各服务自行维护。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .account import AccountType
from .gateway_context import (
    ACCOUNT_TYPE_HEADER,
    CLIENT_META_HEADER,
    DEFAULT_MAX_CLIENT_META_HEADER_LENGTH,
    GATEWAY_CONTEXT_HEADERS,
    GATEWAY_TOKEN_HEADER,
    SESSION_ID_HEADER,
    USER_ID_HEADER,
    USERNAME_HEADER,
    build_gateway_context_headers,
)
from .internal_auth import (
    ensure_service_token_configured,
    extract_bearer_token,
    is_token_matched,
    normalize_service_token,
    parse_bearer_token,
)
from .network import (
    TrustedProxyNetwork,
    is_trusted_proxy,
    is_valid_ip,
    parse_forwarded_for,
    parse_trusted_proxy_networks,
    resolve_client_ip,
)
from .session import (
    SessionContext,
    get_active_session_from_cache,
    get_active_session_from_cache_key,
    get_session_from_cache,
    get_session_from_cache_key,
    get_user_session_cutoff,
    is_session_revoked_by_cutoff,
    session_cache_key,
    session_cache_keys,
    user_session_cutoff_key,
)
from .session_binding import verify_gateway_session_binding
from .settings_validation import (
    DEFAULT_LOCAL_ENVS,
    DEFAULT_WEAK_OBJECT_STORAGE_CREDENTIAL_PAIRS,
    DEFAULT_WEAK_PASSWORDS,
    DEFAULT_WEAK_SERVICE_TOKENS,
    normalize_environment,
    should_enforce_strict_security,
    validate_default_user_password_strength,
    validate_object_storage_credentials_strength,
    validate_service_token_strength,
    validate_session_auth_bypass_disabled,
)

if TYPE_CHECKING:
    from .dependencies import (
        PermissionAwareSession,
        require_account_types,
        require_permissions,
        require_roles,
    )
    from .fastapi import build_service_token_dependency, verify_service_token_value
    from .gateway_session import (
        GatewaySessionHeaders,
        build_gateway_session_context,
        parse_gateway_session_headers,
        resolve_gateway_session_id,
    )


def __getattr__(name: str):
    if name in {
        "PermissionAwareSession",
        "require_permissions",
        "require_roles",
        "require_account_types",
    }:
        from .dependencies import (
            PermissionAwareSession,
            require_account_types,
            require_permissions,
            require_roles,
        )

        exports = {
            "PermissionAwareSession": PermissionAwareSession,
            "require_permissions": require_permissions,
            "require_roles": require_roles,
            "require_account_types": require_account_types,
        }
        return exports[name]
    if name in {"build_service_token_dependency", "verify_service_token_value"}:
        from .fastapi import build_service_token_dependency, verify_service_token_value

        exports = {
            "build_service_token_dependency": build_service_token_dependency,
            "verify_service_token_value": verify_service_token_value,
        }
        return exports[name]
    if name in {
        "GatewaySessionHeaders",
        "build_gateway_session_context",
        "parse_gateway_session_headers",
        "resolve_gateway_session_id",
    }:
        from .gateway_session import (
            GatewaySessionHeaders,
            build_gateway_session_context,
            parse_gateway_session_headers,
            resolve_gateway_session_id,
        )

        exports = {
            "GatewaySessionHeaders": GatewaySessionHeaders,
            "build_gateway_session_context": build_gateway_session_context,
            "parse_gateway_session_headers": parse_gateway_session_headers,
            "resolve_gateway_session_id": resolve_gateway_session_id,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AccountType",
    "PermissionAwareSession",
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
    "verify_gateway_session_binding",
    "require_permissions",
    "require_roles",
    "require_account_types",
    "ensure_service_token_configured",
    "extract_bearer_token",
    "is_token_matched",
    "normalize_service_token",
    "parse_bearer_token",
    "ACCOUNT_TYPE_HEADER",
    "CLIENT_META_HEADER",
    "DEFAULT_MAX_CLIENT_META_HEADER_LENGTH",
    "GATEWAY_CONTEXT_HEADERS",
    "GATEWAY_TOKEN_HEADER",
    "SESSION_ID_HEADER",
    "USER_ID_HEADER",
    "USERNAME_HEADER",
    "build_gateway_context_headers",
    "GatewaySessionHeaders",
    "build_gateway_session_context",
    "parse_gateway_session_headers",
    "resolve_gateway_session_id",
    "build_service_token_dependency",
    "TrustedProxyNetwork",
    "is_trusted_proxy",
    "is_valid_ip",
    "parse_forwarded_for",
    "parse_trusted_proxy_networks",
    "resolve_client_ip",
    "DEFAULT_LOCAL_ENVS",
    "DEFAULT_WEAK_OBJECT_STORAGE_CREDENTIAL_PAIRS",
    "DEFAULT_WEAK_PASSWORDS",
    "DEFAULT_WEAK_SERVICE_TOKENS",
    "normalize_environment",
    "should_enforce_strict_security",
    "validate_default_user_password_strength",
    "validate_object_storage_credentials_strength",
    "validate_service_token_strength",
    "validate_session_auth_bypass_disabled",
    "verify_service_token_value",
]
