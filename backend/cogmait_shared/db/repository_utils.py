"""跨服务共享的仓储层工具。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import is_dataclass
from typing import Any, ClassVar, TypeVar, cast

from pydantic import TypeAdapter

from ..core.collections import deduplicate_preserving_order, restore_input_order

RecordT = TypeVar("RecordT")


class BaseRepositoryMapper:
    """提供 ORM -> 领域记录 的基础字段映射能力。"""

    _adapter_cache: ClassVar[dict[type[object], TypeAdapter[Any]]] = {}

    @staticmethod
    def to_kwargs(entry: object, fields: Iterable[str]) -> dict[str, Any]:
        """按字段白名单提取对象属性。"""

        return {field: getattr(entry, field) for field in fields}

    @classmethod
    def _get_adapter(cls, record_type: type[RecordT]) -> TypeAdapter[Any]:
        cached = cls._adapter_cache.get(cast(type[object], record_type))
        if cached is not None:
            return cached
        adapter = TypeAdapter(record_type)
        cls._adapter_cache[cast(type[object], record_type)] = adapter
        return adapter

    @classmethod
    def to_record(
        cls,
        record_type: type[RecordT],
        entry: object,
        fields: Iterable[str],
        *,
        validate: bool = False,
        strict: bool = False,
    ) -> RecordT:
        """使用字段白名单构造记录对象，可选执行 Pydantic 类型校验。"""

        payload = cls.to_kwargs(entry, fields)
        return cls.record_from_kwargs(
            record_type,
            payload,
            validate=validate,
            strict=strict,
        )

    @classmethod
    def record_from_kwargs(
        cls,
        record_type: type[RecordT],
        payload: dict[str, Any],
        *,
        validate: bool = False,
        strict: bool = False,
    ) -> RecordT:
        """使用 payload 构造记录对象，可选执行 Pydantic 类型校验。"""

        if not validate:
            return record_type(**payload)
        adapter = cls._get_adapter(record_type)
        # 标准 dataclass 在 strict=True 下要求输入必须是实例，不接受 dict。
        # 仓储映射场景输入天然是 dict，这里兼容降级 strict，避免 dataclass_exact_type。
        effective_strict = strict and not is_dataclass(record_type)
        return cast(RecordT, adapter.validate_python(payload, strict=effective_strict))


def escape_like(value: str) -> str:
    """转义 LIKE 模式中的通配符字符。"""

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def apply_field_updates(
    entry: object,
    payload: object,
    fields: Iterable[str],
    *,
    null_fields: Iterable[str] = (),
    transforms: Mapping[str, Callable[[Any], Any]] | None = None,
) -> None:
    """按白名单把 payload 中的非 None 字段写入 ORM 实体。"""

    null_field_set = set(null_fields)
    for field in fields:
        if field in null_field_set:
            setattr(entry, field, None)
            continue
        value = getattr(payload, field, None)
        if value is None:
            continue
        if transforms and field in transforms:
            value = transforms[field](value)
        setattr(entry, field, value)


def mark_entity_soft_deleted(entry: Any, *, operator: int | None) -> None:
    """标记 ORM 实体为软删除并写入操作人。"""

    entry.is_deleted = True
    entry.updated_by = operator


__all__ = [
    "BaseRepositoryMapper",
    "apply_field_updates",
    "deduplicate_preserving_order",
    "escape_like",
    "mark_entity_soft_deleted",
    "restore_input_order",
]
