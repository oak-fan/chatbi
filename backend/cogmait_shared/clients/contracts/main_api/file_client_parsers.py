"""InternalFileClient 的响应解析辅助。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ....core.coercion import parse_strict_int
from ....core.datetime_utils import parse_datetime
from ....core.naming import camel_to_snake_dict
from ....files import FileRecord, FileUploadResult, PresignedUrl
from .errors import FileClientError

__all__ = [
    "_ChunkPartUploadResult",
    "_ChunkUploadInitResult",
    "_parse_chunk_part_upload_result",
    "_parse_chunk_upload_abort_result",
    "_parse_chunk_upload_complete_result",
    "_parse_chunk_upload_init_result",
    "_parse_deleted_count",
    "_parse_file_manage_list",
    "_parse_file_record",
    "_parse_file_records",
    "_parse_marked_count",
    "_parse_presigned_batch",
]


@dataclass(slots=True)
class _ChunkUploadInitResult:
    """分块上传初始化响应载荷。"""

    upload_id: str
    part_size: int
    total_parts: int


@dataclass(slots=True)
class _ChunkPartUploadResult:
    """分块上传分片响应载荷。"""

    upload_id: str
    part_number: int
    uploaded_parts: int
    total_parts: int


def _require_mapping(data: dict[str, Any] | None, *, message: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise FileClientError(message)
    return data


def _parse_int_field(raw_value: Any, *, invalid_message: str, default: int = 0) -> int:
    if raw_value is None:
        return default
    parsed = parse_strict_int(raw_value)
    if parsed is None:
        raise FileClientError(invalid_message)
    return parsed


def _parse_non_empty_str(raw_value: Any, *, missing_message: str) -> str:
    if not isinstance(raw_value, str):
        raise FileClientError(missing_message)
    value = raw_value.strip()
    if not value:
        raise FileClientError(missing_message)
    return value


def _parse_optional_str(raw_value: Any, *, invalid_message: str) -> str | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise FileClientError(invalid_message)
    normalized = raw_value.strip()
    return normalized or None


def _build_file_record(payload: dict[str, Any], *, invalid_message: str) -> FileRecord:
    try:
        return FileRecord.from_wire(payload)
    except (TypeError, ValueError) as exc:
        raise FileClientError(invalid_message) from exc


def _parse_file_record(data: dict[str, Any] | None) -> FileRecord:
    """解析单文件查询响应。"""
    record_payload = _require_mapping(data, message="响应缺少文件数据")
    return _build_file_record(record_payload, invalid_message="响应中的文件记录格式非法")


def _parse_file_records(data: dict[str, Any] | None) -> list[FileRecord]:
    """解析批量文件查询响应。"""
    payload = _require_mapping(data, message="响应缺少 files 列表")
    files = payload.get("files", [])
    if not isinstance(files, list):
        raise FileClientError("响应缺少 files 列表")
    records: list[FileRecord] = []
    for item in files:
        item_payload = _require_mapping(item, message="响应中的 files 项格式非法")
        records.append(
            _build_file_record(item_payload, invalid_message="响应中的 files 项格式非法")
        )
    return records


def _parse_file_manage_list(data: dict[str, Any] | None) -> tuple[list[FileRecord], int]:
    """解析文件管理分页响应。"""
    payload = _require_mapping(data, message="响应缺少文件列表数据")
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise FileClientError("响应缺少 items 列表")

    total = _parse_int_field(payload.get("total"), invalid_message="响应中的 total 字段非法")
    if total < 0:
        raise FileClientError("响应中的 total 字段非法")

    records: list[FileRecord] = []
    for item in items:
        item_payload = _require_mapping(item, message="响应中的 items 项格式非法")
        records.append(
            _build_file_record(item_payload, invalid_message="响应中的 items 项格式非法")
        )
    return records, total


def _parse_presigned_batch(data: dict[str, Any] | None) -> dict[int, PresignedUrl]:
    """解析批量预签名响应。"""
    payload = _require_mapping(data, message="响应缺少 items 列表")
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise FileClientError("响应缺少 items 列表")
    result: dict[int, PresignedUrl] = {}
    for item in items:
        item_payload = _require_mapping(item, message="响应中的 items 项格式非法")
        normalized = camel_to_snake_dict(item_payload)
        file_id = _parse_int_field(
            normalized.get("file_id"), invalid_message="响应中的 file_id 非法"
        )
        if file_id <= 0:
            raise FileClientError("响应中的 file_id 非法")
        try:
            result[file_id] = PresignedUrl.from_wire(item_payload)
        except (TypeError, ValueError) as exc:
            raise FileClientError("响应中的预签名数据格式非法") from exc
    return result


def _parse_deleted_count(data: dict[str, Any] | None) -> int:
    """解析删除结果数量。"""
    payload = _require_mapping(data, message="响应缺少 deleted 字段")
    deleted = payload.get("deleted")
    if deleted is None:
        raise FileClientError("响应缺少 deleted 字段")
    deleted_count = _parse_int_field(deleted, invalid_message="响应中的 deleted 字段非法")
    if deleted_count < 0:
        raise FileClientError("响应中的 deleted 字段非法")
    return deleted_count


def _parse_marked_count(data: dict[str, Any] | None) -> int:
    """解析标记临时文件结果数量。"""
    payload = _require_mapping(data, message="响应缺少 marked 字段")
    marked = payload.get("marked")
    if marked is None:
        raise FileClientError("响应缺少 marked 字段")
    marked_count = _parse_int_field(marked, invalid_message="响应中的 marked 字段非法")
    if marked_count < 0:
        raise FileClientError("响应中的 marked 字段非法")
    return marked_count


def _parse_chunk_upload_init_result(data: dict[str, Any] | None) -> _ChunkUploadInitResult:
    """解析分块上传初始化响应。"""
    payload = _require_mapping(data, message="响应缺少分块初始化数据")
    normalized = camel_to_snake_dict(payload)
    upload_id = _parse_non_empty_str(
        normalized.get("upload_id"),
        missing_message="响应缺少 upload_id",
    )
    part_size = _parse_int_field(
        normalized.get("part_size"), invalid_message="分块初始化响应字段格式非法"
    )
    total_parts = _parse_int_field(
        normalized.get("total_parts"), invalid_message="分块初始化响应字段格式非法"
    )
    if part_size <= 0:
        raise FileClientError("响应缺少有效 part_size")
    if total_parts <= 0:
        raise FileClientError("响应缺少有效 total_parts")
    return _ChunkUploadInitResult(
        upload_id=upload_id,
        part_size=part_size,
        total_parts=total_parts,
    )


def _parse_chunk_part_upload_result(data: dict[str, Any] | None) -> _ChunkPartUploadResult:
    """解析分块上传分片响应。"""
    payload = _require_mapping(data, message="分块上传响应数据不合法")
    normalized = camel_to_snake_dict(payload)
    upload_id = _parse_non_empty_str(
        normalized.get("upload_id"), missing_message="分块上传响应缺少 upload_id"
    )
    part_number = _parse_int_field(
        normalized.get("part_number"), invalid_message="分块上传响应字段格式非法"
    )
    uploaded_parts = _parse_int_field(
        normalized.get("uploaded_parts"), invalid_message="分块上传响应字段格式非法"
    )
    total_parts = _parse_int_field(
        normalized.get("total_parts"), invalid_message="分块上传响应字段格式非法"
    )
    if part_number <= 0:
        raise FileClientError("分块上传响应缺少有效 part_number")
    if uploaded_parts <= 0:
        raise FileClientError("分块上传响应缺少有效 uploaded_parts")
    if total_parts <= 0:
        raise FileClientError("分块上传响应缺少有效 total_parts")
    if uploaded_parts > total_parts:
        raise FileClientError("分块上传响应 uploaded_parts 超出 total_parts")
    return _ChunkPartUploadResult(
        upload_id=upload_id,
        part_number=part_number,
        uploaded_parts=uploaded_parts,
        total_parts=total_parts,
    )


def _parse_chunk_upload_complete_result(data: dict[str, Any] | None) -> FileUploadResult:
    """解析分块上传完成响应。"""
    payload = _require_mapping(data, message="响应缺少 file 字段")
    file_payload = payload.get("file")
    if not isinstance(file_payload, dict):
        raise FileClientError("响应缺少 file 字段")
    return _parse_upload_result(file_payload)


def _parse_chunk_upload_abort_result(data: dict[str, Any] | None) -> bool:
    """解析分块上传中止响应。"""
    payload = _require_mapping(data, message="响应中的 aborted 字段非法")
    aborted = payload.get("aborted")
    if not isinstance(aborted, bool):
        raise FileClientError("响应中的 aborted 字段非法")
    return aborted


def _parse_upload_result(item: dict[str, Any]) -> FileUploadResult:
    """解析单文件上传结果。"""
    normalized = camel_to_snake_dict(item)
    record_payload = normalized.get("record")
    record_data = _require_mapping(record_payload, message="响应缺少文件记录")
    record = _build_file_record(record_data, invalid_message="响应中的文件记录格式非法")
    raw_expires_at = normalized.get("expires_at")
    parsed_expires_at = parse_datetime(raw_expires_at)
    if raw_expires_at is not None and parsed_expires_at is None:
        raise FileClientError("响应中的 expires_at 字段非法")
    presigned_url = _parse_optional_str(
        normalized.get("presigned_url"),
        invalid_message="响应中的 presigned_url 字段非法",
    )
    return FileUploadResult(
        record=record,
        presigned_url=presigned_url,
        expires_at=parsed_expires_at,
        extra=None,
    )
