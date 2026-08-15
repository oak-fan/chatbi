"""统一内容提取相关领域对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ContentExtractMode(StrEnum):
    """统一内容提取模式。"""

    NORMAL = "normal"
    FAST = "fast"


class ContentExtractProvider(StrEnum):
    """统一内容提取内部 provider。"""

    MINERU = "mineru"
    RAPIDOCR = "rapidocr"


@dataclass(slots=True)
class ContentExtractLocatorSpan:
    """解析文本在源文档中的页码与页内位置。"""

    start: int
    end: int
    page: int
    left: float | None = None
    top: float | None = None
    right: float | None = None
    bottom: float | None = None

    def __post_init__(self) -> None:
        self.start = _normalize_non_negative_int(self.start, field_name="start")
        self.end = _normalize_non_negative_int(self.end, field_name="end")
        if self.end < self.start:
            raise ValueError("end 不能小于 start")
        self.page = _normalize_positive_int(self.page, field_name="page")
        self.left = _normalize_optional_float(self.left, field_name="left")
        self.top = _normalize_optional_float(self.top, field_name="top")
        self.right = _normalize_optional_float(self.right, field_name="right")
        self.bottom = _normalize_optional_float(self.bottom, field_name="bottom")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "start": self.start,
            "end": self.end,
            "page": self.page,
        }
        if (
            self.left is not None
            and self.top is not None
            and self.right is not None
            and self.bottom is not None
        ):
            payload.update(
                {
                    "left": self.left,
                    "top": self.top,
                    "right": self.right,
                    "bottom": self.bottom,
                }
            )
        return payload


@dataclass(slots=True)
class MinerUExtractOptions:
    """MinerU 提取参数。"""

    language: str | None = None

    def __post_init__(self) -> None:
        self.language = _normalize_optional_str(self.language, field_name="language")


@dataclass(slots=True)
class RapidOCRExtractOptions:
    """RapidOCR 提取参数。"""

    force_ocr: bool | None = None
    page_num_list: list[int] | None = None

    def __post_init__(self) -> None:
        if self.force_ocr is not None and not isinstance(self.force_ocr, bool):
            raise ValueError("force_ocr 必须为布尔值")
        self.page_num_list = _normalize_page_num_list(self.page_num_list)


@dataclass(slots=True)
class ContentExtractRequest:
    """统一内容提取请求。"""

    file_id: int
    save_result: bool = False
    save_result_is_temporary: bool = False
    save_result_ttl_seconds: int | None = None
    operator_id: int | None = None
    mode: ContentExtractMode = ContentExtractMode.NORMAL
    mineru_options: MinerUExtractOptions | None = None
    rapidocr_options: RapidOCRExtractOptions | None = None

    def __post_init__(self) -> None:
        if isinstance(self.file_id, bool) or not isinstance(self.file_id, int) or self.file_id <= 0:
            raise ValueError("file_id 必须为正整数")
        if not isinstance(self.save_result, bool):
            raise ValueError("save_result 必须为布尔值")
        if not isinstance(self.save_result_is_temporary, bool):
            raise ValueError("save_result_is_temporary 必须为布尔值")
        if self.save_result_ttl_seconds is not None and (
            isinstance(self.save_result_ttl_seconds, bool)
            or not isinstance(self.save_result_ttl_seconds, int)
            or self.save_result_ttl_seconds <= 0
        ):
            raise ValueError("save_result_ttl_seconds 必须为正整数")
        if self.operator_id is not None and (
            isinstance(self.operator_id, bool)
            or not isinstance(self.operator_id, int)
            or self.operator_id <= 0
        ):
            raise ValueError("operator_id 必须为正整数")
        if not isinstance(self.mode, ContentExtractMode):
            self.mode = ContentExtractMode(str(self.mode).strip().lower())
        if self.mineru_options is None:
            self.mineru_options = MinerUExtractOptions()
        if self.rapidocr_options is None:
            self.rapidocr_options = RapidOCRExtractOptions()


@dataclass(slots=True)
class ContentExtractResult:
    """统一内容提取结果。"""

    success: bool
    source_file_id: int
    source_file_name: str
    provider_used: ContentExtractProvider
    content_text: str
    saved_file_id: int | None = None
    locator_spans: list[ContentExtractLocatorSpan] = field(default_factory=list)


def _normalize_optional_str(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须为字符串")
    normalized = value.strip()
    return normalized or None


def _normalize_non_negative_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} 必须为非负整数")
    return value


def _normalize_positive_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} 必须为正整数")
    return value


def _normalize_optional_float(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} 必须为数字")
    normalized = float(value)
    if normalized < 0 or normalized > 1:
        raise ValueError(f"{field_name} 必须在 0 到 1 之间")
    return normalized


def _normalize_page_num_list(value: list[int] | None) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("page_num_list 必须为非负整数列表")

    normalized: list[int] = []
    seen: set[int] = set()
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise ValueError("page_num_list 必须为非负整数列表")
        if item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


__all__ = [
    "ContentExtractLocatorSpan",
    "ContentExtractRequest",
    "ContentExtractMode",
    "MinerUExtractOptions",
    "ContentExtractProvider",
    "ContentExtractResult",
    "RapidOCRExtractOptions",
]
