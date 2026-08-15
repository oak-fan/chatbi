"""基于共享仓储实现的缓存服务。"""

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from .models import RedisZSetRangeResult
from .repository import CacheRepository

_SCRIPT_POP_ZSET_MEMBERS_BY_SCORE = (
    "local zset = KEYS[1];"
    "local max_score = ARGV[1];"
    "local count = tonumber(ARGV[2]);"
    "local members = redis.call("
    "'ZRANGEBYSCORE', zset, '-inf', max_score, 'LIMIT', 0, count"
    ");"
    "if #members == 0 then return {}; end;"
    "redis.call('ZREM', zset, unpack(members));"
    "return members;"
)
_SCRIPT_INCREMENT_WITH_EXPIRE = (
    "local key = KEYS[1];"
    "local ttl_seconds = tonumber(ARGV[1]);"
    "local value = redis.call('INCR', key);"
    "if ttl_seconds and ttl_seconds > 0 then "
    "redis.call('EXPIRE', key, ttl_seconds);"
    "end;"
    "return value;"
)
_SCRIPT_FIXED_WINDOW_LIMIT = (
    "local current = redis.call('INCR', KEYS[1]);"
    "if current == 1 then "
    "redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]));"
    "end;"
    "if current > tonumber(ARGV[2]) then return 0; end;"
    "return 1;"
)
_SCRIPT_REFRESH_LOCK = (
    "if redis.call('GET', KEYS[1]) == ARGV[1] then "
    "return redis.call('EXPIRE', KEYS[1], ARGV[2]); "
    "else "
    "return 0; "
    "end"
)
_SCRIPT_SLIDING_WINDOW_LIMIT = (
    "local key = KEYS[1];"
    "local now_ms = tonumber(ARGV[1]);"
    "local window_ms = tonumber(ARGV[2]);"
    "local member = ARGV[3];"
    "local threshold = tonumber(ARGV[4]);"
    "local ttl_seconds = tonumber(ARGV[5]);"
    "local window_start = now_ms - window_ms;"
    "redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start);"
    "redis.call('ZADD', key, now_ms, member);"
    "local current = redis.call('ZCARD', key);"
    "redis.call('EXPIRE', key, ttl_seconds);"
    "if current > threshold then return {current, 1}; end;"
    "return {current, 0};"
)
_SCRIPT_CONSUME_VALUE_AND_REMOVE_SET_MEMBERS_BY_JSON_FIELD = """
local value_key = KEYS[1]
local set_key_prefix = ARGV[1]
local field_name = ARGV[2]
local first_member = ARGV[3]
local second_member = ARGV[4]
local raw = redis.call('GET', value_key)
if not raw then
    return nil
end
redis.call('DEL', value_key)
local ok, payload = pcall(cjson.decode, raw)
if ok and payload and payload[field_name] then
    local field_value = tostring(payload[field_name])
    redis.call('SREM', set_key_prefix .. field_value, first_member)
    if second_member and second_member ~= "" then
        redis.call('SREM', set_key_prefix .. field_value, second_member)
    end
end
return raw
"""
_SCRIPT_DELETE_VALUE_AND_REMOVE_SET_MEMBERS_BY_JSON_FIELD = """
local value_key = KEYS[1]
local set_key_prefix = ARGV[1]
local field_name = ARGV[2]
local first_member = ARGV[3]
local second_member = ARGV[4]
local raw = redis.call('GET', value_key)
if not raw then
    return 0
end
redis.call('DEL', value_key)
local ok, payload = pcall(cjson.decode, raw)
if ok and payload and payload[field_name] then
    local field_value = tostring(payload[field_name])
    redis.call('SREM', set_key_prefix .. field_value, first_member)
    if second_member and second_member ~= "" then
        redis.call('SREM', set_key_prefix .. field_value, second_member)
    end
end
return 1
"""
_SCRIPT_POP_ZSET_MEMBERS_WHEN_COUNT_EXCEEDS = """
local sessions_key = KEYS[1]
local max_count = tonumber(ARGV[1])
if not max_count or max_count < 1 then
    return {}
end
local count = redis.call('ZCARD', sessions_key)
local overflow = count - max_count
if overflow <= 0 then
    return {}
end
local stale = redis.call('ZRANGE', sessions_key, 0, overflow - 1)
if #stale == 0 then
    return {}
end
redis.call('ZREM', sessions_key, unpack(stale))
return stale
"""


def _decode_script_member(item: Any) -> str:
    if isinstance(item, bytes):
        return item.decode()
    return str(item)


class CacheService:
    """向业务层暴露稳定、有限的缓存操作能力。"""

    def __init__(self, repo: CacheRepository) -> None:
        self._repo = repo

    def build_key(self, key: str) -> str:
        return self._repo.build_key(key)

    async def get_value(self, key: str) -> str | None:
        return await self._repo.get_value(key)

    async def set_value(
        self,
        key: str,
        value: str,
        ttl: int | timedelta | None = 600,
        *,
        persist: bool = False,
    ) -> None:
        await self._repo.set_entry(key, value, ttl=ttl, persist=persist)

    async def acquire_lock(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        return await self._repo.acquire_lock(key, value, ttl_seconds=ttl_seconds)

    async def release_lock(self, key: str, value: str) -> bool:
        return await self._repo.release_lock(key, value)

    async def set_json(
        self,
        key: str,
        data: Any,
        ttl: int | timedelta | None = 600,
        *,
        persist: bool = False,
    ) -> None:
        await self._repo.set_json(key, data, ttl=ttl, persist=persist)

    async def get_json(self, key: str) -> Any | None:
        return await self._repo.get_json(key)

    async def add_set_members(
        self,
        key: str,
        *members: str,
        ttl: int | timedelta | None = None,
        persist: bool = False,
    ) -> int:
        return await self._repo.add_set_members(key, *members, ttl=ttl, persist=persist)

    async def get_set_members(self, key: str) -> set[str]:
        return await self._repo.get_set_members(key)

    async def add_zset_members(
        self,
        key: str,
        members: Mapping[str | bytes, float],
        ttl: int | timedelta | None = None,
        *,
        persist: bool = False,
    ) -> int:
        return await self._repo.add_zset_members(key, members, ttl=ttl, persist=persist)

    async def get_zset_range(
        self,
        key: str,
        start: int,
        end: int,
        *,
        with_scores: bool = False,
        desc: bool = False,
    ) -> RedisZSetRangeResult:
        return await self._repo.get_zset_range(key, start, end, with_scores=with_scores, desc=desc)

    async def remove_zset_members(self, key: str, *members: str) -> int:
        return await self._repo.remove_zset_members(key, *members)

    async def delete(self, key: str) -> bool:
        return await self._repo.delete_entry(key)

    async def increment_with_expire(self, key: str, *, ttl_seconds: int) -> int:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        result = await self._repo.eval(_SCRIPT_INCREMENT_WITH_EXPIRE, [key], [str(ttl_seconds)])
        return int(result or 0)

    async def check_fixed_window_limit(
        self,
        key: str,
        *,
        window_seconds: int,
        max_requests: int,
    ) -> bool:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        if max_requests <= 0:
            raise ValueError("max_requests must be > 0")
        result = await self._repo.eval(
            _SCRIPT_FIXED_WINDOW_LIMIT,
            [key],
            [str(window_seconds), str(max_requests)],
        )
        return int(result or 0) == 1

    async def refresh_lock(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        result = await self._repo.eval(_SCRIPT_REFRESH_LOCK, [key], [value, str(ttl_seconds)])
        return int(result or 0) > 0

    async def check_sliding_window_limit(
        self,
        key: str,
        *,
        timestamp_ms: int,
        window_ms: int,
        member: str,
        threshold: int,
        ttl_seconds: int,
    ) -> tuple[int, bool]:
        if window_ms <= 0:
            raise ValueError("window_ms must be > 0")
        if not member:
            raise ValueError("member must not be empty")
        if threshold <= 0:
            raise ValueError("threshold must be > 0")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        result = await self._repo.eval(
            _SCRIPT_SLIDING_WINDOW_LIMIT,
            [key],
            [
                str(timestamp_ms),
                str(window_ms),
                member,
                str(threshold),
                str(ttl_seconds),
            ],
        )
        if not isinstance(result, list | tuple) or len(result) != 2:
            raise TypeError("sliding window script must return count and limited flag")
        count = int(result[0])
        limited_flag = int(result[1])
        if count < 0:
            raise ValueError("sliding window count must be >= 0")
        if limited_flag not in {0, 1}:
            raise ValueError("sliding window limited flag must be 0 or 1")
        return count, limited_flag == 1

    async def consume_json_value_and_remove_field_index_members(
        self,
        key: str,
        *,
        set_key_prefix: str,
        field_name: str,
        members: tuple[str, str | None],
    ) -> str | None:
        result = await self._repo.eval(
            _SCRIPT_CONSUME_VALUE_AND_REMOVE_SET_MEMBERS_BY_JSON_FIELD,
            [key],
            [
                self._repo.build_key(set_key_prefix),
                field_name,
                members[0],
                members[1] or "",
            ],
        )
        if result is None:
            return None
        if isinstance(result, bytes):
            return result.decode()
        return str(result)

    async def delete_json_value_and_remove_field_index_members(
        self,
        key: str,
        *,
        set_key_prefix: str,
        field_name: str,
        members: tuple[str, str | None],
    ) -> bool:
        result = await self._repo.eval(
            _SCRIPT_DELETE_VALUE_AND_REMOVE_SET_MEMBERS_BY_JSON_FIELD,
            [key],
            [
                self._repo.build_key(set_key_prefix),
                field_name,
                members[0],
                members[1] or "",
            ],
        )
        return int(result or 0) > 0

    async def pop_zset_members_when_count_exceeds(self, key: str, *, max_count: int) -> list[str]:
        result = await self._repo.eval(
            _SCRIPT_POP_ZSET_MEMBERS_WHEN_COUNT_EXCEEDS,
            [key],
            [str(max_count)],
        )
        if result is None:
            return []
        if not isinstance(result, list | tuple):
            raise TypeError("zset pop excess script must return a sequence")
        return [_decode_script_member(item) for item in result]

    async def pop_zset_members_by_score(
        self,
        key: str,
        *,
        max_score: float,
        count: int,
    ) -> list[str]:
        if count <= 0:
            return []
        result = await self._repo.eval(
            _SCRIPT_POP_ZSET_MEMBERS_BY_SCORE,
            [key],
            [str(max_score), str(count)],
        )
        if result is None:
            return []
        if not isinstance(result, list | tuple):
            raise TypeError("zset pop script must return a sequence")
        return [_decode_script_member(item) for item in result]
