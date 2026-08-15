"""Lightweight shared type aliases that must not import web framework modules."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer, WithJsonSchema


def _serialize_snowflake_id(value: Any) -> str:
    return str(value)


def _reject_bool_snowflake_id(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("ID 不能为布尔值")
    return value


SnowflakeID = Annotated[
    int,
    BeforeValidator(_reject_bool_snowflake_id),
    PlainSerializer(_serialize_snowflake_id, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string"}),
]


__all__ = ["SnowflakeID"]
