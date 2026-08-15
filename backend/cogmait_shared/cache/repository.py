"""跨服务复用的异步 Redis 仓储封装。"""

from collections.abc import Awaitable, Mapping
from datetime import timedelta
from json import dumps, loads
from typing import Any, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from ..observability.logging import logger
from ..redis_namespace import normalize_redis_namespace, prefix_redis_name
from ._repository_utils import (
    RedisDict,
    RedisMapping,
    _decode_map_values,
    _describe_json_raw,
    _normalize_set_expire,
    _normalize_ttl,
    _normalize_zset_items,
    _resolve_ttl_policy,
    _to_optional_text,
    _to_redis_dict,
    _to_text,
    _to_zset_dict,
)
from .models import CacheEntry, RedisZSetRangeItem, RedisZSetRangeResult


class CacheRepository:
    """提供带过期时间处理的高层 Redis 操作。"""

    def __init__(self, redis: Redis, *, key_prefix: str = "") -> None:
        self._redis = redis
        self._key_prefix = normalize_redis_namespace(key_prefix)

    def _key(self, key: str) -> str:
        return prefix_redis_name(key, self._key_prefix)

    def _keys(self, keys: list[str]) -> list[str]:
        return [self._key(key) for key in keys]

    def build_key(self, key: str) -> str:
        return self._key(key)

    async def get_value(self, key: str) -> str | None:
        raw_value = await self._redis.get(self._key(key))
        return _to_optional_text(cast(str | bytes | None, raw_value))

    async def get_entry(self, key: str) -> CacheEntry:
        value = await self.get_value(key)
        return CacheEntry(key=key, value=value)

    async def set_entry(
        self,
        key: str,
        value: str,
        ttl: int | timedelta | None = None,
        *,
        persist: bool = False,
    ) -> None:
        ex = _normalize_set_expire(ttl, persist)
        await self._redis.set(name=self._key(key), value=value, ex=ex)

    async def set_if_absent(
        self,
        key: str,
        value: str,
        ttl: int | timedelta | None = None,
        *,
        persist: bool = False,
    ) -> bool:
        ex = _normalize_set_expire(ttl, persist)
        created = await self._redis.set(name=self._key(key), value=value, nx=True, ex=ex)
        return bool(created)

    async def acquire_lock(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        created = await cast(
            Awaitable[bool | None],
            self._redis.set(name=self._key(key), value=value, nx=True, ex=ttl_seconds),
        )
        return bool(created)

    async def release_lock(self, key: str, value: str) -> bool:
        script = (
            "if redis.call('GET', KEYS[1]) == ARGV[1] then "
            "  return redis.call('DEL', KEYS[1]); "
            "else "
            "  return 0; "
            "end"
        )
        removed = await self.eval(script, [key], [value])
        return int(removed) > 0

    async def get_values(self, keys: list[str]) -> list[str | None]:
        if not keys:
            return []
        values = await cast(Awaitable[list[str | bytes | None]], self._redis.mget(self._keys(keys)))
        return [_to_optional_text(value) for value in values]

    async def set_json(
        self,
        key: str,
        data: Any,
        ttl: int | timedelta | None = None,
        *,
        persist: bool = False,
    ) -> None:
        ex = _normalize_set_expire(ttl, persist)
        await self._redis.set(name=self._key(key), value=dumps(data, ensure_ascii=False), ex=ex)

    async def get_json(self, key: str) -> Any | None:
        redis_key = self._key(key)
        raw = await self._redis.get(redis_key)
        if raw is None:
            return None
        try:
            return loads(raw)
        except (TypeError, ValueError) as exc:
            logger.warning(
                "缓存 JSON 反序列化失败，按缓存未命中处理并清理 key={} raw={} error_type={}",
                _describe_cache_key(redis_key),
                _describe_json_raw(raw),
                exc.__class__.__name__,
            )
            try:
                await cast(Awaitable[int], self._redis.delete(redis_key))
            except (RedisError, OSError, TimeoutError, ConnectionError) as cleanup_exc:
                logger.warning(
                    "清理损坏缓存 JSON 失败 key={} error_type={}",
                    _describe_cache_key(redis_key),
                    cleanup_exc.__class__.__name__,
                )
            return None

    async def set_map(
        self,
        key: str,
        mapping: RedisMapping,
        ttl: int | timedelta | None = None,
        *,
        persist: bool = False,
    ) -> None:
        if not mapping:
            await self.delete_entry(key)
            return
        redis_mapping: RedisDict = _to_redis_dict(mapping)
        redis_key = self._key(key)
        await cast(Awaitable[int], self._redis.hset(name=redis_key, mapping=redis_mapping))
        await _apply_ttl(self._redis, redis_key, ttl, persist)

    async def get_map(self, key: str) -> dict[str, str]:
        raw_map = await cast(
            Awaitable[dict[str | bytes, str | bytes]],
            self._redis.hgetall(self._key(key)),
        )
        return _decode_map_values(raw_map)

    async def delete_map_fields(self, key: str, *fields: str) -> int:
        if not fields:
            return 0
        removed = await cast(Awaitable[int], self._redis.hdel(self._key(key), *fields))
        return int(removed)

    async def add_set_members(
        self,
        key: str,
        *members: str,
        ttl: int | timedelta | None = None,
        persist: bool = False,
    ) -> int:
        if not members:
            return 0
        redis_key = self._key(key)
        added = await cast(Awaitable[int], self._redis.sadd(redis_key, *members))
        await _apply_ttl(self._redis, redis_key, ttl, persist)
        return int(added)

    async def get_set_members(self, key: str) -> set[str]:
        raw_members = await cast(Awaitable[set[str | bytes]], self._redis.smembers(self._key(key)))
        return {_to_text(member) for member in raw_members}

    async def remove_set_members(self, key: str, *members: str) -> int:
        if not members:
            return 0
        removed = await cast(Awaitable[int], self._redis.srem(self._key(key), *members))
        return int(removed)

    async def add_zset_members(
        self,
        key: str,
        members: Mapping[str | bytes, float],
        ttl: int | timedelta | None = None,
        *,
        persist: bool = False,
    ) -> int:
        if not members:
            return 0
        normalized_members = _to_zset_dict(members)
        redis_key = self._key(key)
        added = await cast(
            Awaitable[int],
            self._redis.zadd(redis_key, mapping=cast(Mapping[Any, Any], normalized_members)),
        )
        await _apply_ttl(self._redis, redis_key, ttl, persist)
        return int(added)

    async def get_zset_range(
        self,
        key: str,
        start: int,
        end: int,
        *,
        with_scores: bool = False,
        desc: bool = False,
    ) -> RedisZSetRangeResult:
        if desc:
            result = await cast(
                Awaitable[list[RedisZSetRangeItem]],
                self._redis.zrevrange(self._key(key), start, end, withscores=with_scores),
            )
            return _normalize_zset_items(list(result))
        result = await cast(
            Awaitable[list[RedisZSetRangeItem]],
            self._redis.zrange(self._key(key), start, end, withscores=with_scores),
        )
        return _normalize_zset_items(list(result))

    async def increment_zset_score(
        self,
        key: str,
        member: str,
        increment: float,
        ttl: int | timedelta | None = None,
        *,
        persist: bool = False,
    ) -> float:
        """增加ZSet成员的分数。"""
        redis_key = self._key(key)
        new_score = await cast(Awaitable[float], self._redis.zincrby(redis_key, increment, member))
        await _apply_ttl(self._redis, redis_key, ttl, persist)
        return float(new_score)

    async def remove_zset_members(self, key: str, *members: str) -> int:
        if not members:
            return 0
        removed = await cast(Awaitable[int], self._redis.zrem(self._key(key), *members))
        return int(removed)

    async def pop_zset_min(
        self,
        key: str,
        count: int,
        *,
        with_scores: bool = True,
    ) -> RedisZSetRangeResult:
        if count <= 0:
            return []
        popped = await cast(
            Awaitable[list[tuple[str | bytes, float]]],
            self._redis.zpopmin(self._key(key), count=count),
        )
        if not with_scores:
            return [_to_text(member) for member, _score in popped]
        return [(_to_text(member), score) for member, score in popped]

    async def remove_zset_by_score(self, key: str, min_score: float, max_score: float) -> int:
        removed = await self._redis.zremrangebyscore(self._key(key), min_score, max_score)
        return int(removed)

    async def get_zset_members_by_score(
        self,
        key: str,
        min_score: float,
        max_score: float,
        *,
        offset: int = 0,
        count: int | None = None,
    ) -> list[str]:
        if count is None:
            result = await self._redis.zrangebyscore(self._key(key), min_score, max_score)
        else:
            result = await self._redis.zrangebyscore(
                self._key(key),
                min_score,
                max_score,
                start=offset,
                num=count,
            )
        return [_to_text(cast(str | bytes, item)) for item in cast(list[Any], result or [])]

    async def get_zset_score(self, key: str, member: str) -> float | None:
        score = await self._redis.zscore(self._key(key), member)
        return float(score) if score is not None else None

    async def eval(self, script: str, keys: list[str], args: list[Any]) -> Any:
        normalized_keys = self._keys(keys)
        result = self._redis.eval(script, len(normalized_keys), *normalized_keys, *args)
        return await cast(Awaitable[Any], result)

    async def delete_entry(self, key: str) -> bool:
        removed = await self._redis.delete(self._key(key))
        return removed > 0

    async def increment(self, key: str, amount: int = 1) -> int:
        value = await cast(Awaitable[int], self._redis.incrby(self._key(key), amount))
        return int(value)

    async def set_expire(self, key: str, ttl: int | timedelta) -> bool:
        normalized = _normalize_ttl(ttl)
        if normalized is None:
            raise ValueError("设置过期时间时 ttl 必须为正数")
        result = await self._redis.expire(self._key(key), normalized)
        return bool(result)

    async def get_zset_count(self, key: str) -> int:
        count = await cast(Awaitable[int], self._redis.zcard(self._key(key)))
        return int(count)


def _describe_cache_key(redis_key: str) -> str:
    prefix, separator, tail = redis_key.rpartition(":")
    if not separator or len(tail) < 32:
        return redis_key
    if prefix.endswith(":sha256"):
        return redis_key
    return f"{prefix}{separator}****redacted****"


async def _apply_ttl(
    redis: Redis,
    key: str,
    ttl: int | timedelta | None,
    persist: bool,
) -> None:
    """根据 ttl/persist 参数统一设置过期时间。"""

    normalized, should_persist = _resolve_ttl_policy(ttl, persist)
    if normalized is not None:
        await redis.expire(key, normalized)
    elif should_persist:
        await redis.persist(key)
