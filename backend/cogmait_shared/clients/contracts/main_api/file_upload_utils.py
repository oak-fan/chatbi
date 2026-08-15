"""InternalFileClient 上传流程的纯函数工具。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, BinaryIO, Protocol, TypeGuard

from ....files.constants import FILE_CHUNK_MAX_PART_SIZE, FILE_CHUNK_MIN_PART_SIZE
from .errors import FileClientError


class UploadFilePayloadLike(Protocol):
    filename: str
    content: bytes | None
    content_type: str | None
    stream: BinaryIO | None
    file_size: int | None
    relative_path: str | None
    root_directory: str | None


def _normalize_optional_text(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise FileClientError(f"{field_name} 必须是字符串")
    normalized = value.strip()
    return normalized or None


def validate_upload_file_payload(file: UploadFilePayloadLike) -> None:
    """校验上传文件载荷的基本字段。"""
    if not isinstance(file.filename, str):
        raise FileClientError("文件名必须是字符串")
    if not file.filename.strip():
        raise FileClientError("文件名不能为空")
    if file.file_size is not None and not _is_positive_int(file.file_size):
        raise FileClientError("file_size 必须为正整数")
    _normalize_optional_text(file.content_type, field_name="content_type")
    if file.content is not None and file.stream is not None:
        raise FileClientError("content 与 stream 只能提供其一")
    if file.content is None and file.stream is None:
        raise FileClientError("文件内容不能为空")
    if file.content is not None and not file.content:
        raise FileClientError("文件内容不能为空")
    if file.stream is not None and file.file_size is None:
        raise FileClientError("stream 模式必须提供有效 file_size")
    if (
        file.content is not None
        and file.file_size is not None
        and file.file_size != len(file.content)
    ):
        raise FileClientError("file_size 与 content 长度不一致")


def resolve_upload_file_size(file: UploadFilePayloadLike) -> int:
    """解析上传文件大小。"""
    if file.content is not None:
        return len(file.content)
    if not _is_positive_int(file.file_size):
        raise FileClientError("文件大小必须为正整数")
    return file.file_size


def _is_positive_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def iter_upload_chunks(
    *,
    file: UploadFilePayloadLike,
    file_size: int,
    part_size: int,
) -> Iterator[bytes]:
    """按分块大小生成上传二进制片段。"""
    if file.content is not None:
        for offset in range(0, file_size, part_size):
            yield file.content[offset : offset + part_size]
        return
    if file.stream is None:
        raise FileClientError("文件内容不能为空")
    remaining = file_size
    while remaining > 0:
        chunk = file.stream.read(min(part_size, remaining))
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise FileClientError("stream.read 必须返回 bytes")
        if len(chunk) > remaining:
            raise FileClientError("stream.read 返回的数据超出 file_size")
        yield chunk
        remaining -= len(chunk)
    if remaining != 0:
        raise FileClientError("stream 数据长度与 file_size 不一致")


def resolve_preferred_part_size(file_size: int, *, small_file_threshold_bytes: int) -> int | None:
    """小文件优先减少分片数量，超阈值文件走服务端默认分片策略。"""
    if file_size > small_file_threshold_bytes:
        return None
    if file_size < FILE_CHUNK_MIN_PART_SIZE:
        return None
    return min(file_size, FILE_CHUNK_MAX_PART_SIZE)


def build_upload_init_payload(
    *,
    file: UploadFilePayloadLike,
    business_value: str,
    is_temporary: bool,
    ttl_seconds: int | None,
    operator_id: int | None,
    small_file_threshold_bytes: int,
) -> tuple[int, dict[str, Any]]:
    """构建上传初始化请求体。"""
    validate_upload_file_payload(file)
    file_size = resolve_upload_file_size(file)
    content_type = _normalize_optional_text(file.content_type, field_name="content_type")
    relative_path = _normalize_optional_text(file.relative_path, field_name="relative_path")
    root_directory = _normalize_optional_text(file.root_directory, field_name="root_directory")
    payload: dict[str, Any] = {
        "filename": file.filename.strip(),
        "file_size": file_size,
        "content_type": content_type,
        "business_code": business_value,
        "is_temporary": is_temporary,
    }
    if relative_path is not None:
        payload["relative_path"] = relative_path
    if root_directory is not None:
        payload["root_directory"] = root_directory
    preferred_part_size = resolve_preferred_part_size(
        file_size, small_file_threshold_bytes=small_file_threshold_bytes
    )
    if preferred_part_size is not None:
        payload["part_size"] = preferred_part_size
    if ttl_seconds is not None:
        payload["ttl_seconds"] = ttl_seconds
    if operator_id is not None:
        payload["operator_id"] = operator_id
    return file_size, payload
