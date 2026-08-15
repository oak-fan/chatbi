"""通用集合处理工具。"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from typing import TypeVar

KeyT = TypeVar("KeyT", bound=Hashable)
RecordT = TypeVar("RecordT")


def deduplicate_preserving_order(values: Iterable[KeyT]) -> list[KeyT]:
    """保留首次出现顺序并去重。"""

    return list(dict.fromkeys(values))


def restore_input_order(
    records: Iterable[RecordT],
    ordered_keys: Iterable[KeyT],
    *,
    key: Callable[[RecordT], KeyT],
) -> list[RecordT]:
    """按输入 key 顺序恢复记录列表，缺失记录会被跳过。"""

    records_by_key = {key(record): record for record in records}
    return [records_by_key[item] for item in ordered_keys if item in records_by_key]


__all__ = ["deduplicate_preserving_order", "restore_input_order"]
