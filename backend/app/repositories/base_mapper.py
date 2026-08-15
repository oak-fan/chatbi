"""仓储层记录映射工具。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import is_dataclass
from typing import Any, ClassVar, TypeVar, cast

from pydantic import TypeAdapter

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
        effective_strict = strict and not is_dataclass(record_type)
        return cast(RecordT, adapter.validate_python(payload, strict=effective_strict))


__all__ = ["BaseRepositoryMapper"]
