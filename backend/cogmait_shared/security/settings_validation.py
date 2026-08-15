"""跨服务复用的安全配置校验工具。"""

from __future__ import annotations

from collections.abc import Collection

DEFAULT_LOCAL_ENVS: frozenset[str] = frozenset(
    {"local", "development", "dev", "test", "testing", "ci"}
)
DEFAULT_WEAK_SERVICE_TOKENS: frozenset[str] = frozenset(
    {"", "change-me-internal", "changeme", "default"}
)
DEFAULT_WEAK_PASSWORDS: frozenset[str] = frozenset(
    {"", "123456", "password", "admin", "changeme", "change-me"}
)
DEFAULT_WEAK_OBJECT_STORAGE_CREDENTIAL_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("admin", "password"),
        ("minioadmin", "minioadmin"),
        ("localminioadmin", "LocalMinioPassw0rd!"),
    }
)


def normalize_environment(environment: str | None) -> str:
    """标准化环境名称。"""
    return (environment or "").strip().lower()


def should_enforce_strict_security(
    *,
    environment: str | None,
    strict_mode: bool | None = None,
    local_envs: Collection[str] = DEFAULT_LOCAL_ENVS,
) -> bool:
    """判断是否应执行 non-local 严格安全约束。"""
    if strict_mode is not None:
        return strict_mode
    local_env_set = {item.strip().lower() for item in local_envs if item.strip()}
    return normalize_environment(environment) not in local_env_set


def validate_service_token_strength(
    service_token: str | None,
    *,
    weak_tokens: Collection[str] = DEFAULT_WEAK_SERVICE_TOKENS,
    min_length: int = 24,
) -> None:
    """校验内部服务 token 强度。"""
    token = (service_token or "").strip()
    normalized_weak_tokens = {item.strip() for item in weak_tokens}
    if token in normalized_weak_tokens or len(token) < min_length:
        raise ValueError("non-local 环境必须配置强 SERVICE_TOKEN（长度>=24 且非默认值）")


def validate_session_auth_bypass_disabled(allow_session_auth_bypass: bool) -> None:
    """校验会话绕过仅允许 local 环境开启。"""
    if allow_session_auth_bypass:
        raise ValueError("ALLOW_SESSION_AUTH_BYPASS 仅允许在 local 环境开启")


def validate_default_user_password_strength(
    default_user_password: str | None,
    *,
    weak_passwords: Collection[str] = DEFAULT_WEAK_PASSWORDS,
    min_length: int = 8,
) -> None:
    """校验默认密码强度。"""
    normalized_weak_passwords = {item.strip().lower() for item in weak_passwords}
    password = (default_user_password or "").strip()
    if password.lower() in normalized_weak_passwords or len(password) < min_length:
        raise ValueError("non-local 环境必须配置强 DEFAULT_USER_PASSWORD（长度>=8 且非弱口令）")


def validate_object_storage_credentials_strength(
    object_storage_access_key: str | None,
    object_storage_secret_key: str | None,
    *,
    weak_passwords: Collection[str] = DEFAULT_WEAK_PASSWORDS,
    weak_pairs: Collection[tuple[str, str]] = DEFAULT_WEAK_OBJECT_STORAGE_CREDENTIAL_PAIRS,
    min_password_length: int = 12,
) -> None:
    """校验 non-local 环境的对象存储凭证强度。"""
    normalized_user = (object_storage_access_key or "").strip()
    if not normalized_user:
        raise ValueError("non-local 环境必须配置 OBJECT_STORAGE_ACCESS_KEY")

    normalized_password = (object_storage_secret_key or "").strip()
    normalized_weak_passwords = {item.strip().lower() for item in weak_passwords}
    if (
        normalized_password.lower() in normalized_weak_passwords
        or len(normalized_password) < min_password_length
    ):
        raise ValueError(
            "non-local 环境必须配置强 OBJECT_STORAGE_SECRET_KEY（长度>=12 且非弱口令）"
        )

    normalized_weak_pairs = {
        (user.strip().lower(), password.strip().lower()) for user, password in weak_pairs
    }
    if (normalized_user.lower(), normalized_password.lower()) in normalized_weak_pairs:
        raise ValueError(
            "non-local 环境禁止使用默认对象存储凭证组合，"
            "请显式覆盖 OBJECT_STORAGE_ACCESS_KEY / OBJECT_STORAGE_SECRET_KEY"
        )


__all__ = [
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
]
