"""文件服务相关的共享数据模型。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from ..core.coercion import parse_required_int, parse_strict_bool
from ..core.model_normalization import (
    normalize_optional_datetime,
    normalize_optional_int,
    normalize_optional_str,
    normalize_required_str,
    normalize_wire_payload,
)
from ..core.types import SnowflakeID


def _normalize_bool(raw_value: Any, *, field_name: str) -> bool:
    # Wire 模型需要兼容历史 JSON/查询串载荷；写入入口仍由各服务单独收紧校验。
    parsed = parse_strict_bool(raw_value)
    if parsed is not None:
        return parsed
    raise ValueError(f"{field_name} must be boolean-like")


def _normalize_is_deleted(raw_is_deleted: Any) -> bool:
    if raw_is_deleted is None:
        return False
    parsed = parse_strict_bool(raw_is_deleted)
    if parsed is not None:
        return parsed
    raise ValueError("is_deleted must be boolean-like")


@dataclass(slots=True)
class FileRecord:
    """跨服务文件记录契约；不暴露文件中心表结构所有权。"""

    id: SnowflakeID
    original_name: str
    stored_filename: str
    storage_key: str | None
    bucket_name: str | None
    business_code: str
    file_size: int
    file_extension: str
    is_temporary: bool
    expires_at: datetime | None
    content_hash: str | None = None
    hash_algorithm: str | None = None
    hash_calculated_at: datetime | None = None
    created_at: datetime | None = None
    created_by: int | None = None
    updated_at: datetime | None = None
    updated_by: int | None = None
    is_deleted: bool = False
    relative_path: str | None = None
    root_directory: str | None = None

    def __post_init__(self) -> None:
        self._normalize_required_fields()
        self._normalize_flags_and_owners()
        self._normalize_datetimes()

    def _normalize_required_fields(self) -> None:
        object.__setattr__(self, "id", parse_required_int(self.id, field_name="id"))
        if self.id <= 0:
            raise ValueError("id must be greater than 0")

        object.__setattr__(
            self,
            "original_name",
            normalize_required_str(self.original_name, field_name="original_name"),
        )
        object.__setattr__(
            self,
            "stored_filename",
            normalize_required_str(self.stored_filename, field_name="stored_filename"),
        )
        object.__setattr__(
            self,
            "business_code",
            normalize_required_str(self.business_code, field_name="business_code").upper(),
        )
        object.__setattr__(
            self,
            "file_extension",
            normalize_required_str(self.file_extension, field_name="file_extension"),
        )
        object.__setattr__(
            self,
            "content_hash",
            normalize_optional_str(self.content_hash, field_name="content_hash"),
        )
        object.__setattr__(
            self,
            "hash_algorithm",
            normalize_optional_str(self.hash_algorithm, field_name="hash_algorithm"),
        )
        object.__setattr__(
            self,
            "file_size",
            parse_required_int(self.file_size, field_name="file_size"),
        )
        if self.file_size < 0:
            raise ValueError("file_size must be >= 0")

    def _normalize_flags_and_owners(self) -> None:
        object.__setattr__(
            self, "is_temporary", _normalize_bool(self.is_temporary, field_name="is_temporary")
        )
        object.__setattr__(self, "is_deleted", _normalize_is_deleted(self.is_deleted))
        object.__setattr__(
            self,
            "storage_key",
            normalize_optional_str(self.storage_key, field_name="storage_key"),
        )
        object.__setattr__(
            self,
            "bucket_name",
            normalize_optional_str(self.bucket_name, field_name="bucket_name"),
        )
        object.__setattr__(
            self,
            "relative_path",
            normalize_optional_str(self.relative_path, field_name="relative_path"),
        )
        object.__setattr__(
            self,
            "root_directory",
            normalize_optional_str(self.root_directory, field_name="root_directory"),
        )
        object.__setattr__(
            self,
            "created_by",
            normalize_optional_int(self.created_by, field_name="created_by"),
        )
        object.__setattr__(
            self,
            "updated_by",
            normalize_optional_int(self.updated_by, field_name="updated_by"),
        )

    def _normalize_datetimes(self) -> None:
        object.__setattr__(
            self,
            "expires_at",
            normalize_optional_datetime(self.expires_at, field_name="expires_at"),
        )
        object.__setattr__(
            self,
            "hash_calculated_at",
            normalize_optional_datetime(
                self.hash_calculated_at,
                field_name="hash_calculated_at",
            ),
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

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> FileRecord:
        """从接口响应载荷构造文件记录对象。"""
        normalized = normalize_wire_payload(payload)
        return cls(
            id=cast(int, normalized.get("id")),
            original_name=cast(str, normalized.get("original_name")),
            stored_filename=cast(str, normalized.get("stored_filename")),
            storage_key=normalized.get("storage_key"),
            bucket_name=normalized.get("bucket_name"),
            business_code=cast(str, normalized.get("business_code")),
            file_size=cast(int, normalized.get("file_size")),
            file_extension=cast(str, normalized.get("file_extension")),
            is_temporary=cast(bool, normalized.get("is_temporary")),
            expires_at=normalized.get("expires_at"),
            content_hash=normalized.get("content_hash"),
            hash_algorithm=normalized.get("hash_algorithm"),
            hash_calculated_at=normalized.get("hash_calculated_at"),
            created_at=normalized.get("created_at"),
            created_by=normalized.get("created_by"),
            updated_at=normalized.get("updated_at"),
            updated_by=normalized.get("updated_by"),
            is_deleted=cast(bool, normalized.get("is_deleted")),
            relative_path=normalized.get("relative_path"),
            root_directory=normalized.get("root_directory"),
        )


@dataclass(slots=True)
class FileUploadResult:
    """上传文件后的返回结构。"""

    record: FileRecord
    presigned_url: str | None = None
    expires_at: datetime | None = None
    extra: dict[str, Any] | None = None


@dataclass(slots=True)
class PresignedUrl:
    """描述预签名 URL 与其上下文。"""

    url: str
    bucket_name: str
    storage_key: str
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", normalize_required_str(self.url, field_name="url"))
        object.__setattr__(
            self,
            "bucket_name",
            normalize_required_str(self.bucket_name, field_name="bucket_name"),
        )
        object.__setattr__(
            self,
            "storage_key",
            normalize_required_str(self.storage_key, field_name="storage_key"),
        )
        expires_at = normalize_optional_datetime(self.expires_at, field_name="expires_at")
        if expires_at is None:
            raise ValueError("expires_at 不能为空")
        object.__setattr__(self, "expires_at", expires_at)

    @classmethod
    def from_wire(cls, payload: Mapping[str, Any]) -> PresignedUrl:
        """从接口响应载荷构造预签名结果对象。"""
        normalized = normalize_wire_payload(payload)
        return cls(
            url=cast(str, normalized.get("url")),
            bucket_name=cast(str, normalized.get("bucket_name")),
            storage_key=cast(str, normalized.get("storage_key")),
            expires_at=cast(datetime, normalized.get("expires_at")),
        )


__all__ = [
    "FileRecord",
    "FileUploadResult",
    "PresignedUrl",
]
