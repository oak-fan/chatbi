"""PostgreSQL 连接 URL 解析为连接器配置字段。"""

from __future__ import annotations

from urllib.parse import parse_qsl, unquote, urlparse

type PostgresUrlConfig = dict[str, str | int | dict[str, str]]


def parse_postgres_url(url: str) -> PostgresUrlConfig:
    """将 postgresql:// 或 postgresql+asyncpg:// URL 拆成 host/port/database 等。"""
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    if parsed.scheme != "postgresql":
        raise ValueError("仅支持 postgresql:// 或 postgresql+asyncpg:// 连接地址")
    if not parsed.hostname:
        raise ValueError("PostgreSQL 连接地址缺少 host")
    if not parsed.username:
        raise ValueError("PostgreSQL 连接地址缺少 username")
    if parsed.password is None:
        raise ValueError("PostgreSQL 连接地址缺少 password")
    path = (parsed.path or "").lstrip("/")
    if not path:
        raise ValueError("PostgreSQL 连接地址缺少 database")
    extra_params = {
        key: value
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if key and value
    }
    return {
        "host": parsed.hostname,
        "port": int(parsed.port or 5432),
        "database": path,
        "username": unquote(parsed.username),
        "password": unquote(parsed.password),
        "extra_params": extra_params,
    }


__all__ = ["parse_postgres_url"]
