"""Common utility helpers shared across services."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel

__all__ = [
    "snake_to_camel",
    "snake_to_camel_dict",
    "camel_to_snake",
    "camel_to_snake_dict",
]


def snake_to_camel(value: str) -> str:
    """Convert a single snake_case token to camelCase."""

    if "_" not in value:
        return value

    head, *tail = value.split("_")
    normalized_tail = [segment.capitalize() for segment in tail if segment]
    return head + "".join(normalized_tail)


def snake_to_camel_dict(data: Any) -> Any:
    """Recursively convert mapping keys from snake_case to camelCase."""
    return _transform_keys_recursive(data, transform=snake_to_camel)


def camel_to_snake(value: str) -> str:
    """Convert a single camelCase or PascalCase token to snake_case."""

    if "_" in value:
        return value

    result = []
    for idx, ch in enumerate(value):
        if ch.isupper():
            prev_ch = value[idx - 1] if idx > 0 else ""
            next_ch = value[idx + 1] if idx + 1 < len(value) else ""
            should_insert_separator = idx > 0 and (
                prev_ch.islower() or prev_ch.isdigit() or (prev_ch.isupper() and next_ch.islower())
            )
            if should_insert_separator:
                result.append("_")
        result.append(ch.lower())
    return "".join(result)


def camel_to_snake_dict(data: Any) -> Any:
    """Recursively convert mapping keys from camelCase/PascalCase to snake_case."""
    return _transform_keys_recursive(data, transform=camel_to_snake)


def _transform_keys_recursive(
    data: Any,
    *,
    transform: Callable[[str], str],
) -> Any:
    if data is None:
        return None

    if isinstance(data, BaseModel):
        dumped = data.model_dump(mode="python", exclude_none=False)
        return _transform_keys_recursive(dumped, transform=transform)

    if isinstance(data, Mapping):
        converted: dict[Any, Any] = {}
        for key, value in data.items():
            new_key = transform(key) if isinstance(key, str) else key
            converted[new_key] = _transform_keys_recursive(value, transform=transform)
        return converted

    if isinstance(data, Sequence) and not isinstance(data, str | bytes | bytearray):
        converted_items = [_transform_keys_recursive(item, transform=transform) for item in data]
        if isinstance(data, tuple):
            return tuple(converted_items)
        return converted_items

    return data
