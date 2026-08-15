"""缓存操作协议。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Protocol

from .models import RedisZSetRangeResult


class CacheOps(Protocol):
    def build_key(self, key: str) -> str: ...

    async def get_value(self, key: str) -> str | None: ...

    async def set_value(
        self,
        key: str,
        value: str,
        ttl: int | timedelta | None = 600,
        *,
        persist: bool = False,
    ) -> None: ...

    async def acquire_lock(self, key: str, value: str, *, ttl_seconds: int) -> bool: ...

    async def release_lock(self, key: str, value: str) -> bool: ...

    async def set_json(
        self,
        key: str,
        data: Any,
        ttl: int | timedelta | None = 600,
        *,
        persist: bool = False,
    ) -> None: ...

    async def get_json(self, key: str) -> Any | None: ...

    async def add_set_members(
        self,
        key: str,
        *members: str,
        ttl: int | timedelta | None = None,
        persist: bool = False,
    ) -> int: ...

    async def get_set_members(self, key: str) -> set[str]: ...

    async def add_zset_members(
        self,
        key: str,
        members: Mapping[str | bytes, float],
        ttl: int | timedelta | None = None,
        *,
        persist: bool = False,
    ) -> int: ...

    async def get_zset_range(
        self,
        key: str,
        start: int,
        end: int,
        *,
        with_scores: bool = False,
        desc: bool = False,
    ) -> RedisZSetRangeResult: ...

    async def remove_zset_members(self, key: str, *members: str) -> int: ...

    async def delete(self, key: str) -> bool: ...

    async def increment_with_expire(self, key: str, *, ttl_seconds: int) -> int: ...

    async def check_fixed_window_limit(
        self,
        key: str,
        *,
        window_seconds: int,
        max_requests: int,
    ) -> bool: ...

    async def refresh_lock(self, key: str, value: str, *, ttl_seconds: int) -> bool: ...

    async def check_sliding_window_limit(
        self,
        key: str,
        *,
        timestamp_ms: int,
        window_ms: int,
        member: str,
        threshold: int,
        ttl_seconds: int,
    ) -> tuple[int, bool]: ...

    async def pop_zset_members_when_count_exceeds(
        self, key: str, *, max_count: int
    ) -> list[str]: ...

    async def pop_zset_members_by_score(
        self,
        key: str,
        *,
        max_score: float,
        count: int,
    ) -> list[str]: ...


class JsonFieldIndexCacheOps(CacheOps, Protocol):
    """JSON 值与字段索引集合保持一致的原子操作。"""

    async def consume_json_value_and_remove_field_index_members(
        self,
        key: str,
        *,
        set_key_prefix: str,
        field_name: str,
        members: tuple[str, str | None],
    ) -> str | None: ...

    async def delete_json_value_and_remove_field_index_members(
        self,
        key: str,
        *,
        set_key_prefix: str,
        field_name: str,
        members: tuple[str, str | None],
    ) -> bool: ...


__all__ = ["CacheOps", "JsonFieldIndexCacheOps"]
