"""Redis 名称空间辅助函数。"""

from __future__ import annotations


def normalize_redis_namespace(value: str | None) -> str:
    """归一化 Redis 项目前缀，去除空白与首尾冒号。"""
    if value is None:
        return ""
    return str(value).strip().strip(":")


def prefix_redis_name(name: str, namespace: str | None) -> str:
    """为 Redis key/channel/stream 追加统一项目前缀。"""
    normalized_name = str(name).strip()
    if not normalized_name:
        raise ValueError("Redis name must not be blank")
    normalized_namespace = normalize_redis_namespace(namespace)
    if not normalized_namespace:
        return normalized_name
    return f"{normalized_namespace}:{normalized_name}"


__all__ = ["normalize_redis_namespace", "prefix_redis_name"]
