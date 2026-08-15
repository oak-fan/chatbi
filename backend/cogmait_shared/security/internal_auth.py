"""内部服务鉴权解析工具。"""

from __future__ import annotations

import secrets


def normalize_service_token(value: str | None) -> str:
    """标准化服务令牌配置值。"""
    return (value or "").strip()


def ensure_service_token_configured(expected_token: str) -> None:
    """确保服务令牌已配置。"""
    if not expected_token:
        raise ValueError("服务令牌未配置")


def parse_bearer_token(authorization: str | None) -> str | None:
    """解析 Authorization: Bearer <token>，格式不合法时返回空。"""
    if not authorization:
        return None

    parts = authorization.strip().split()
    if len(parts) != 2:
        return None

    scheme, token = parts
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def extract_bearer_token(authorization: str | None) -> str:
    """解析 Authorization: Bearer <token>，格式不合法时抛出错误。"""
    if not authorization:
        raise ValueError("缺少 Authorization 请求头")

    token = parse_bearer_token(authorization)
    if token is None:
        raise ValueError("Authorization 请求头格式非法")
    return token


def is_token_matched(*, token: str, expected_token: str) -> bool:
    """常量时间比较令牌。"""
    return secrets.compare_digest(token, expected_token)


__all__ = [
    "extract_bearer_token",
    "ensure_service_token_configured",
    "is_token_matched",
    "normalize_service_token",
    "parse_bearer_token",
]
