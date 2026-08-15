"""Redis Streams 消息与载荷模型。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from json import JSONDecodeError, dumps, loads
from typing import Any


def _decode(value: str | bytes | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


class StreamMessageDecodeError(ValueError):
    """Redis Stream 消息载荷无法按约定解析。"""


def _load_json_object(
    raw: str | None,
    *,
    field_name: str,
    required: bool,
) -> tuple[dict[str, Any], str | None]:
    if raw is None:
        if required:
            return {}, f"{field_name} 缺失"
        return {}, None
    try:
        value = loads(raw)
    except (JSONDecodeError, TypeError, ValueError):
        return {}, f"{field_name} 不是合法 JSON"
    if not isinstance(value, dict):
        return {}, f"{field_name} 必须为 JSON object"
    return value, None


def _safe_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class StreamPayload:
    """统一的 Redis Streams 入队载荷。"""

    task_type: str
    payload: Mapping[str, Any]
    request_id: str | None = None
    attributes: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task_type, str):
            raise ValueError("task_type 必须为字符串")
        normalized_task_type = self.task_type.strip()
        if not normalized_task_type:
            raise ValueError("task_type 不能为空")
        self.task_type = normalized_task_type

        if not isinstance(self.payload, Mapping):
            raise ValueError("payload 必须为映射类型")

        if self.request_id is not None:
            if not isinstance(self.request_id, str):
                raise ValueError("request_id 提供时必须为字符串")
            normalized_request_id = self.request_id.strip()
            self.request_id = normalized_request_id or None

        if self.attributes is not None and not isinstance(self.attributes, Mapping):
            raise ValueError("attributes 必须为映射类型")

    def to_redis_fields(self) -> dict[str, str]:
        fields: dict[str, str] = {
            "task_type": self.task_type,
            "payload": dumps(self.payload, ensure_ascii=False),
        }
        if self.request_id:
            fields["request_id"] = self.request_id
        if self.attributes:
            fields["attributes"] = dumps(self.attributes, ensure_ascii=False)
        return fields


@dataclass(slots=True)
class StreamMessage:
    """消费 Redis Streams 时的标准化消息体。"""

    stream: str
    message_id: str
    task_type: str | None
    payload: dict[str, Any]
    request_id: str | None
    attributes: dict[str, Any] = field(default_factory=dict)
    retry_count: int | None = None
    decode_error: str | None = None
    raw: dict[str, str | None] = field(default_factory=dict)

    @classmethod
    def from_redis(
        cls,
        stream: str,
        message_id: str,
        data: Mapping[str | bytes, str | bytes],
    ) -> StreamMessage:
        cache: dict[str, str | None] = {}
        for key, value in data.items():
            normalized_key = _decode(key)
            if normalized_key is None:
                continue
            cache[normalized_key] = _decode(value)
        payload, payload_error = _load_json_object(
            cache.get("payload"),
            field_name="payload",
            required=True,
        )
        attributes, attributes_error = _load_json_object(
            cache.get("attributes"),
            field_name="attributes",
            required=False,
        )
        decode_error = (
            "; ".join(error for error in (payload_error, attributes_error) if error) or None
        )
        retry_count = _safe_int(cache.get("retry_count"))

        return cls(
            stream=stream,
            message_id=message_id,
            task_type=cache.get("task_type"),
            payload=payload,
            request_id=cache.get("request_id"),
            attributes=attributes,
            retry_count=retry_count,
            decode_error=decode_error,
            raw=cache,
        )

    def as_tuple(self) -> tuple[str, str]:
        """返回 (stream, message_id) 组合，便于日志与排查。"""
        return self.stream, self.message_id
