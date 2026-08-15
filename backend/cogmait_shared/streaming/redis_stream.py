"""Redis Streams 封装，统一生产者/消费者接口。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import cast

from redis.asyncio import Redis
from redis.exceptions import ResponseError
from redis.typing import EncodableT, FieldT

from ..core.coercion import parse_required_int, parse_strict_bool
from ..redis_namespace import prefix_redis_name
from .models import StreamMessage, StreamPayload

RedisStreamFields = Mapping[str | bytes, str | bytes]
RedisStreamEntries = Iterable[tuple[str | bytes, RedisStreamFields]]
RedisStreamReadResponse = Iterable[tuple[str | bytes, RedisStreamEntries]]


def _to_text(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _parse_xautoclaim_response(response: object) -> tuple[str, RedisStreamEntries]:
    if not isinstance(response, list | tuple) or len(response) < 2:
        raise ValueError("xautoclaim 响应必须包含 next_start_id 和 messages")
    raw_next_start = response[0]
    messages = cast(RedisStreamEntries, response[1])
    if isinstance(raw_next_start, str | bytes):
        return _to_text(raw_next_start), messages
    return str(raw_next_start), messages


@dataclass(slots=True)
class RedisStreamConfig:
    """Redis Streams 读写配置。"""

    stream: str
    group: str
    consumer: str
    block_ms: int = 5000
    count: int = 10
    start_from: str = "0"
    auto_create_group: bool = True
    key_prefix: str = ""

    def __post_init__(self) -> None:
        self._normalize_identity_fields()
        self._normalize_read_options()

    def _normalize_identity_fields(self) -> None:
        if not isinstance(self.stream, str):
            raise ValueError("stream 必须为字符串")
        if not isinstance(self.group, str):
            raise ValueError("group 必须为字符串")
        if not isinstance(self.consumer, str):
            raise ValueError("consumer 必须为字符串")
        if not isinstance(self.start_from, str):
            raise ValueError("start_from 必须为字符串")
        if not isinstance(self.key_prefix, str):
            raise ValueError("key_prefix 必须为字符串")
        self.stream = self.stream.strip()
        self.group = self.group.strip()
        self.consumer = self.consumer.strip()
        self.start_from = self.start_from.strip()
        self.key_prefix = self.key_prefix.strip()

        if not self.stream:
            raise ValueError("stream 不能为空")
        if not self.group:
            raise ValueError("group 不能为空")
        if not self.consumer:
            raise ValueError("consumer 不能为空")
        if not self.start_from:
            raise ValueError("start_from 不能为空")
        self.stream = prefix_redis_name(self.stream, self.key_prefix)

    def _normalize_read_options(self) -> None:
        self.block_ms = parse_required_int(self.block_ms, field_name="block_ms")
        self.count = parse_required_int(self.count, field_name="count")
        parsed_auto_create_group = parse_strict_bool(self.auto_create_group)
        if parsed_auto_create_group is None:
            raise ValueError("auto_create_group 必须为布尔值")
        self.auto_create_group = parsed_auto_create_group
        if self.block_ms < 0:
            raise ValueError("block_ms 必须大于等于 0")
        if self.count < 1:
            raise ValueError("count 必须大于等于 1")


class RedisStreamPublisher:
    """面向业务的 Redis Streams 发布器。"""

    def __init__(
        self,
        redis: Redis,
        *,
        stream: str,
        maxlen: int | None = None,
        approximate: bool = True,
        key_prefix: str = "",
    ) -> None:
        self._redis = redis
        if not isinstance(stream, str):
            raise ValueError("stream 必须为字符串")
        normalized_stream = stream.strip()
        if not normalized_stream:
            raise ValueError("stream 不能为空")
        if maxlen is not None:
            if isinstance(maxlen, bool) or not isinstance(maxlen, int):
                raise ValueError("maxlen 提供时必须为整数")
            if maxlen < 1:
                raise ValueError("maxlen 提供时必须大于等于 1")
        if not isinstance(approximate, bool):
            raise ValueError("approximate 必须为布尔值")
        if not isinstance(key_prefix, str):
            raise ValueError("key_prefix 必须为字符串")

        self._stream = prefix_redis_name(normalized_stream, key_prefix)
        self._maxlen = maxlen
        self._approximate = approximate

    async def publish(self, payload: StreamPayload) -> str:
        """将任务追加到指定 stream。"""
        fields = cast(
            "dict[FieldT, EncodableT]",
            payload.to_redis_fields(),
        )
        message_id = await self._redis.xadd(
            name=self._stream,
            fields=fields,
            maxlen=self._maxlen,
            approximate=self._approximate,
        )
        if isinstance(message_id, bytes):
            return message_id.decode(errors="replace")
        if isinstance(message_id, str):
            return message_id
        return str(message_id)


class RedisStreamConsumer:
    """消费 Redis Streams 的封装，支持自动建组与重试。"""

    def __init__(self, redis: Redis, config: RedisStreamConfig) -> None:
        self._redis = redis
        self._config = config
        self._group_ready = not config.auto_create_group
        self._group_lock = asyncio.Lock()

    async def poll(self) -> list[StreamMessage]:
        """阻塞式读取消息。"""
        await self._ensure_group()
        response = await self._redis.xreadgroup(
            groupname=self._config.group,
            consumername=self._config.consumer,
            streams={self._config.stream: ">"},
            count=self._config.count,
            block=self._config.block_ms,
        )
        return _parse_messages(response)

    async def ack(self, *message_ids: str) -> int:
        """确认消息已处理。"""
        if not message_ids:
            return 0
        acknowledged = await self._redis.xack(
            self._config.stream,
            self._config.group,
            *message_ids,
        )
        return int(acknowledged)

    async def delete(self, *message_ids: str) -> int:
        """从 stream 移除指定消息。"""
        if not message_ids:
            return 0
        removed = await self._redis.xdel(self._config.stream, *message_ids)
        return int(removed)

    async def claim_idle(
        self,
        *,
        min_idle_ms: int,
        count: int | None = None,
        start: str = "0-0",
    ) -> tuple[list[StreamMessage], str]:
        """认领空闲超时的 pending 消息，实现手动重试。"""
        await self._ensure_group()
        raw_response = await self._redis.xautoclaim(
            name=self._config.stream,
            groupname=self._config.group,
            consumername=self._config.consumer,
            min_idle_time=min_idle_ms,
            start_id=start,
            count=count,
        )
        next_start, messages = _parse_xautoclaim_response(raw_response)
        return _parse_stream_only(self._config.stream, messages), next_start

    async def _ensure_group(self) -> None:
        if self._group_ready or not self._config.auto_create_group:
            return
        async with self._group_lock:
            if self._group_ready:
                return
            try:
                await self._redis.xgroup_create(
                    name=self._config.stream,
                    groupname=self._config.group,
                    id=self._config.start_from,
                    mkstream=True,
                )
            except ResponseError as exc:  # pragma: no cover - 仅在并发建组失败时触发
                if "BUSYGROUP" not in str(exc):
                    raise
            self._group_ready = True


def _parse_messages(
    messages: RedisStreamReadResponse | None,
) -> list[StreamMessage]:
    parsed: list[StreamMessage] = []
    for stream, entries in messages or []:
        parsed.extend(_parse_stream_only(_to_text(stream), entries))
    return parsed


def _parse_stream_only(
    stream: str,
    entries: RedisStreamEntries,
) -> list[StreamMessage]:
    result: list[StreamMessage] = []
    for message_id, data in entries:
        result.append(StreamMessage.from_redis(stream, _to_text(message_id), data))
    return result
