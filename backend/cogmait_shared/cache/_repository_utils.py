"""CacheRepository 私有工具函数。"""

from collections.abc import Mapping
from datetime import timedelta
from typing import cast

from .models import RedisZSetRangeItem, RedisZSetRangeResult

RedisMapping = Mapping[str | bytes, bytes | float | int | str]
RedisDict = dict[str | bytes, bytes | float | int | str]


def _to_redis_dict(mapping: RedisMapping) -> RedisDict:
    """Copy Mapping into a concrete dict with the exact Redis value types."""

    return {key: value for key, value in mapping.items()}


def _to_zset_dict(mapping: Mapping[str | bytes, float]) -> dict[str, float]:
    """Normalize zset member keys to str for Redis zadd typing compatibility."""

    normalized: dict[str, float] = {}
    for key, value in mapping.items():
        normalized_key = _to_text(key)
        normalized[normalized_key] = float(value)
    return normalized


def _to_text(value: str | bytes) -> str:
    """Normalize Redis text payload to str."""

    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _to_optional_text(value: str | bytes | None) -> str | None:
    if value is None:
        return None
    return _to_text(value)


def _describe_json_raw(raw: object) -> str:
    if isinstance(raw, bytes):
        return f"bytes(len={len(raw)})"
    if isinstance(raw, str):
        return f"str(len={len(raw)})"
    return type(raw).__name__


def _decode_map_values(raw: Mapping[str | bytes, str | bytes]) -> dict[str, str]:
    decoded: dict[str, str] = {}
    for key, value in raw.items():
        decoded[_to_text(cast(str | bytes, key))] = _to_text(cast(str | bytes, value))
    return decoded


def _normalize_zset_items(items: list[RedisZSetRangeItem]) -> RedisZSetRangeResult:
    normalized: RedisZSetRangeResult = []
    for item in items:
        if isinstance(item, tuple):
            member, score = item
            normalized.append((_to_text(member), score))
            continue
        normalized.append(_to_text(item))
    return normalized


def _normalize_ttl(ttl: int | timedelta | None) -> int | None:
    """将多种 TTL 表达形式转换为秒数。"""

    if ttl is None:
        return None
    if isinstance(ttl, bool):
        raise ValueError("ttl must be integer seconds, timedelta, or None")
    normalized: int
    if isinstance(ttl, timedelta):
        normalized = int(ttl.total_seconds())
    elif isinstance(ttl, int):
        normalized = ttl
    else:
        raise ValueError("ttl must be integer seconds, timedelta, or None")
    if normalized < 0:
        raise ValueError("ttl must be >= 0")
    if normalized == 0:
        return None
    return normalized


def _resolve_ttl_policy(ttl: int | timedelta | None, persist: bool) -> tuple[int | None, bool]:
    normalized = _normalize_ttl(ttl)
    if persist and normalized is not None:
        raise ValueError("persist 模式下请勿同时设置 ttl")
    return normalized, persist and normalized is None


def _normalize_set_expire(
    ttl: int | timedelta | None,
    persist: bool,
) -> int | None:
    normalized, _ = _resolve_ttl_policy(ttl, persist)
    return normalized
