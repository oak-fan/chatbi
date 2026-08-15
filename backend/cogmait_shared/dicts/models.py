"""跨服务共享的字典领域模型。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from ..core.coercion import parse_required_int
from ..core.datetime_utils import serialize_datetime
from ..core.model_normalization import (
    normalize_optional_datetime,
    normalize_optional_str,
    normalize_required_str,
)
from ..core.types import SnowflakeID
from ..enums import DictConfigType
from .value_utils import normalize_dict_value

__all__ = [
    "DictItemDefinition",
    "DictDefinition",
    "DictRefreshResult",
]


def _require_boolean(raw_value: Any, *, field_name: str) -> bool:
    if not isinstance(raw_value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return raw_value


def _normalize_dict_scope(raw_value: Any) -> str:
    return DictConfigType.from_value(raw_value).value


def _require_wire_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("payload 必须为映射类型")
    return dict(payload)


def _require_wire_field(payload: Mapping[str, Any], field_name: str) -> Any:
    if field_name not in payload or payload[field_name] is None:
        raise ValueError(f"{field_name} 不能为空")
    return payload[field_name]


@dataclass(slots=True)
class DictItemDefinition:
    """描述单个字典项。"""

    item_id: SnowflakeID
    dict_id: SnowflakeID
    item_code: str
    item_label: str
    is_enabled: bool
    description: str | None = None
    color: str | None = None
    sort_order: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "item_id",
            parse_required_int(self.item_id, field_name="item_id"),
        )
        object.__setattr__(
            self,
            "dict_id",
            parse_required_int(self.dict_id, field_name="dict_id"),
        )
        object.__setattr__(
            self,
            "item_code",
            normalize_dict_value(self.item_code, field_name="item_code"),
        )
        object.__setattr__(
            self,
            "item_label",
            normalize_required_str(self.item_label, field_name="item_label"),
        )
        object.__setattr__(
            self,
            "description",
            normalize_optional_str(self.description, field_name="description"),
        )
        object.__setattr__(
            self,
            "color",
            normalize_optional_str(self.color, field_name="color"),
        )
        object.__setattr__(
            self,
            "sort_order",
            parse_required_int(self.sort_order, field_name="sort_order"),
        )
        object.__setattr__(
            self,
            "is_enabled",
            _require_boolean(self.is_enabled, field_name="is_enabled"),
        )
        object.__setattr__(
            self,
            "created_at",
            normalize_optional_datetime(self.created_at, field_name="created_at"),
        )
        object.__setattr__(
            self,
            "updated_at",
            normalize_optional_datetime(self.updated_at, field_name="updated_at"),
        )

    def to_wire(self) -> dict[str, Any]:
        payload = {field: getattr(self, field) for field in self.__dataclass_fields__}
        payload["created_at"] = serialize_datetime(self.created_at)
        payload["updated_at"] = serialize_datetime(self.updated_at)
        return payload

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> DictItemDefinition:
        normalized = _require_wire_mapping(payload)
        return cls(
            item_id=cast(int, _require_wire_field(normalized, "item_id")),
            dict_id=cast(int, _require_wire_field(normalized, "dict_id")),
            item_code=cast(str, _require_wire_field(normalized, "item_code")),
            item_label=cast(str, _require_wire_field(normalized, "item_label")),
            description=normalized.get("description"),
            color=normalized.get("color"),
            sort_order=cast(int, _require_wire_field(normalized, "sort_order")),
            is_enabled=_require_boolean(normalized.get("is_enabled"), field_name="is_enabled"),
            created_at=normalized.get("created_at"),
            updated_at=normalized.get("updated_at"),
        )


@dataclass(slots=True)
class DictDefinition:
    """包含字典基础信息及其字典项。"""

    dict_id: SnowflakeID
    dict_type: str
    dict_name: str
    dict_scope: str
    is_enabled: bool
    remark: str | None = None
    items: list[DictItemDefinition] = field(default_factory=list)
    version_token: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dict_id",
            parse_required_int(self.dict_id, field_name="dict_id"),
        )
        object.__setattr__(
            self,
            "dict_type",
            normalize_required_str(self.dict_type, field_name="dict_type"),
        )
        object.__setattr__(
            self,
            "dict_name",
            normalize_required_str(self.dict_name, field_name="dict_name"),
        )
        object.__setattr__(self, "dict_scope", _normalize_dict_scope(self.dict_scope))
        object.__setattr__(
            self,
            "is_enabled",
            _require_boolean(self.is_enabled, field_name="is_enabled"),
        )
        object.__setattr__(
            self,
            "remark",
            normalize_optional_str(self.remark, field_name="remark"),
        )
        object.__setattr__(
            self,
            "version_token",
            normalize_optional_str(self.version_token, field_name="version_token"),
        )
        object.__setattr__(
            self,
            "created_at",
            normalize_optional_datetime(self.created_at, field_name="created_at"),
        )
        object.__setattr__(
            self,
            "updated_at",
            normalize_optional_datetime(self.updated_at, field_name="updated_at"),
        )

        normalized_items: list[DictItemDefinition] = []
        for item in self.items:
            if isinstance(item, DictItemDefinition):
                normalized_items.append(item)
                continue
            if isinstance(item, Mapping):
                normalized_items.append(DictItemDefinition.from_wire(item))
                continue
            raise ValueError("items 必须包含 DictItemDefinition 或映射类型")
        object.__setattr__(self, "items", normalized_items)

    def to_wire(self, *, include_items: bool = True) -> dict[str, Any]:
        payload = {field: getattr(self, field) for field in self.__dataclass_fields__}
        payload["created_at"] = serialize_datetime(self.created_at)
        payload["updated_at"] = serialize_datetime(self.updated_at)
        if include_items:
            payload["items"] = [item.to_wire() for item in self.items]
        else:
            payload["items"] = []
        return payload

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> DictDefinition:
        normalized = _require_wire_mapping(payload)
        items_payload = normalized.get("items")
        if items_payload is None:
            raise ValueError("items 不能为空")
        if not isinstance(items_payload, list):
            raise ValueError("items 必须为列表")
        resolved_dict_scope = _normalize_dict_scope(normalized.get("dict_scope"))
        return cls(
            dict_id=cast(int, normalized.get("dict_id")),
            dict_type=cast(str, normalized.get("dict_type")),
            dict_name=cast(str, normalized.get("dict_name")),
            dict_scope=resolved_dict_scope,
            is_enabled=_require_boolean(normalized.get("is_enabled"), field_name="is_enabled"),
            remark=normalized.get("remark"),
            items=items_payload,
            version_token=normalized.get("version_token"),
            created_at=normalized.get("created_at"),
            updated_at=normalized.get("updated_at"),
        )

    def ensure_version_token(self, defaults: Iterable[datetime | None]) -> None:
        if self.version_token:
            return
        latest = max((dt for dt in defaults if dt is not None), default=None)
        if latest:
            self.version_token = serialize_datetime(latest)


@dataclass(slots=True)
class DictRefreshResult:
    """缓存刷新结果描述。"""

    dict_type: str
    version_token: str | None = None

    def to_wire(self) -> dict[str, Any]:
        return {"dict_type": self.dict_type, "version_token": self.version_token}
