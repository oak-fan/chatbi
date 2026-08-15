"""文件名与对象键工具。"""

from __future__ import annotations

from datetime import datetime

from ..core.datetime_utils import now_local
from .constants import FILE_OBJECT_KEY_MAX_LENGTH
from .enums import FileBusinessType


def sanitize_filename(name: str) -> str:
    """净化原始文件名，避免路径穿越与控制字符。"""

    if not name:
        return "unnamed"
    # 统一路径分隔符后仅保留最后一段，避免目录逃逸。
    leaf_name = name.replace("\\", "/").split("/")[-1]
    cleaned = "".join(
        char for char in leaf_name if char not in {"/", "\\", "\x00"} and char.isprintable()
    )
    normalized = cleaned.strip().strip(".")
    if not normalized or normalized in {".", ".."}:
        return "unnamed"
    return normalized


def build_object_key(
    *,
    business_code: FileBusinessType,
    stored_filename: str,
    original_name: str,
    date: datetime | None = None,
) -> str:
    """根据业务类型与存储名生成 MinIO 对象键。"""

    prefix = _build_object_prefix(
        business_code=business_code,
        stored_filename=stored_filename,
        date=date,
    )
    max_filename_length = FILE_OBJECT_KEY_MAX_LENGTH - len(prefix) - 1
    safe_name = _truncate_filename(sanitize_filename(original_name), max_filename_length)
    return f"{prefix}/{safe_name}"


def _build_object_prefix(
    *,
    business_code: FileBusinessType,
    stored_filename: str,
    date: datetime | None,
) -> str:
    """构造对象键前缀：业务类型/日期/存储名。"""
    date_part = (date or now_local()).strftime("%Y/%m/%d")
    business_segment = business_code.name.lower()
    return f"{business_segment}/{date_part}/{stored_filename}"


def _truncate_filename(filename: str, max_length: int) -> str:
    """按最大长度截断文件名，尽量保留扩展名。"""
    if max_length <= 0:
        return "file"
    if len(filename) <= max_length:
        return filename
    stem, dot, suffix = filename.rpartition(".")
    if not dot:
        return filename[:max_length]
    extension = f".{suffix}"
    remain = max_length - len(extension)
    if remain <= 0:
        return filename[:max_length]
    truncated_stem = stem[:remain]
    return f"{truncated_stem}{extension}"


__all__ = ["sanitize_filename", "build_object_key"]
