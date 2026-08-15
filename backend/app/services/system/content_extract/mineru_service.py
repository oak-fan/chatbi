"""MinerU 内容提取适配器。"""

from __future__ import annotations

import mimetypes
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cogmait_shared.clients.contracts.main_api import UploadFilePayload
from cogmait_shared.files import FileRecord
from cogmait_shared.observability.logging import logger

from ....core.config import settings
from ....domain.system import ContentExtractLocatorSpan, ContentExtractProvider
from ....processors.mineru_client import (
    MinerUArtifact,
    MinerUClient,
    MinerUClientError,
    MinerUProcessingResult,
)

__all__ = ["MinerUService", "MinerUServiceError"]

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})
_SUPPORTED_FILE_EXTENSIONS = frozenset({"pdf", "doc", "docx"})
_TEXT_KEYS = ("text", "content", "md_content", "markdown", "value")
_BBOX_KEYS = ("bbox", "box", "position", "layout_bbox")
_PAGE_ONE_BASED_KEYS = ("page", "page_no", "page_number")
_PAGE_ZERO_BASED_KEYS = ("page_idx", "page_index")
_WIDTH_KEYS = ("width", "page_width", "w")
_HEIGHT_KEYS = ("height", "page_height", "h")


class MinerUServiceError(Exception):
    """MinerU 服务调用失败。"""


@dataclass(slots=True)
class MinerUExtractResult:
    """MinerU 标准化后的提取结果。"""

    success: bool
    source_file_id: int
    source_file_name: str
    provider_used: ContentExtractProvider
    content_text: str
    artifacts: list[UploadFilePayload] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    locator_spans: list[ContentExtractLocatorSpan] = field(default_factory=list)


class MinerUService:
    """负责本地 MinerU 调用与产物封装。"""

    provider = ContentExtractProvider.MINERU

    def __init__(
        self,
        *,
        mineru_client: MinerUClient | None = None,
    ) -> None:
        self._mineru_client = mineru_client

    def is_available(self) -> bool:
        if self._mineru_client is not None:
            return True
        return bool(_normalize_optional_text(settings.mineru_local_api_base))

    @staticmethod
    def supports_file(file_record: FileRecord) -> bool:
        return file_record.file_extension.lower().removeprefix(".") in _SUPPORTED_FILE_EXTENSIONS

    async def extract_from_local_file(
        self,
        *,
        source_file_id: int,
        source_file_name: str,
        local_file_path: Path,
        work_dir: Path,
        language: str | None = None,
    ) -> MinerUExtractResult:
        """基于本地文件执行 MinerU 提取。"""
        try:
            processing_result = await self._get_client().process_file_to_markdown(
                local_file_path.as_posix(),
                output_dir=work_dir,
                language=_normalize_optional_text(language),
                cleanup_local_output=False,
            )
            artifacts = self._build_artifacts(
                processing_result=processing_result,
                source_name=source_file_name,
            )
            metadata = self._build_metadata(
                source_file_name=source_file_name,
                processing_result=processing_result,
                artifacts=artifacts,
            )
            return MinerUExtractResult(
                success=True,
                source_file_id=source_file_id,
                source_file_name=source_file_name,
                provider_used=self.provider,
                content_text=processing_result.content,
                artifacts=artifacts,
                metadata=metadata,
                locator_spans=self._build_locator_spans(
                    content_text=processing_result.content,
                    metadata=metadata,
                ),
            )
        except MinerUClientError as exc:
            raise MinerUServiceError(str(exc)) from exc
        except Exception as exc:
            logger.opt(exception=exc).error("MinerU 解析失败")
            raise MinerUServiceError(f"MinerU 解析失败：{exc}") from exc

    def _build_artifacts(
        self,
        *,
        processing_result: MinerUProcessingResult,
        source_name: str,
    ) -> list[UploadFilePayload]:
        source_stem = Path(source_name).stem or "document"
        return [
            self._convert_artifact(item, source_stem=source_stem)
            for item in processing_result.artifacts
        ]

    @staticmethod
    def _build_metadata(
        *,
        source_file_name: str,
        processing_result: MinerUProcessingResult,
        artifacts: list[UploadFilePayload],
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "source_file_extension": Path(source_file_name).suffix.removeprefix(".").lower(),
            "artifact_filenames": [artifact.filename for artifact in artifacts],
        }
        layout = processing_result.metadata.get("layout")
        if isinstance(layout, dict):
            metadata["layout"] = layout
        content_list = processing_result.metadata.get("content_list")
        if isinstance(content_list, list):
            metadata["content_list"] = content_list
        image_paths = processing_result.metadata.get("image_paths")
        if isinstance(image_paths, list):
            metadata["image_filenames"] = [
                Path(path).name for path in image_paths if isinstance(path, str)
            ]
        image_filenames = processing_result.metadata.get("image_filenames")
        if isinstance(image_filenames, list):
            metadata["image_filenames"] = [
                item for item in image_filenames if isinstance(item, str)
            ]
        if processing_result.output_dir is not None:
            metadata["output_dir"] = processing_result.output_dir
        return metadata

    def _get_client(self) -> MinerUClient:
        if self._mineru_client is None:
            self._mineru_client = MinerUClient()
        return self._mineru_client

    @staticmethod
    def _build_locator_spans(
        *,
        content_text: str,
        metadata: Mapping[str, Any],
    ) -> list[ContentExtractLocatorSpan]:
        content_list = metadata.get("content_list")
        if not isinstance(content_list, list) or not content_text:
            return []

        page_sizes = _collect_page_sizes(metadata.get("layout"))
        cursor = 0
        spans: list[ContentExtractLocatorSpan] = []
        for item in content_list:
            if not isinstance(item, Mapping):
                continue
            text = _extract_content_text(item)
            page = _extract_page_number(item)
            if text is None or page is None:
                continue
            start = content_text.find(text, cursor)
            if start < 0:
                start = content_text.find(text)
            if start < 0:
                continue
            end = start + len(text)
            cursor = end
            bbox = _normalize_bbox(_extract_bbox(item), page_sizes.get(page))
            try:
                spans.append(
                    ContentExtractLocatorSpan(
                        start=start,
                        end=end,
                        page=page,
                        left=bbox[0] if bbox is not None else None,
                        top=bbox[1] if bbox is not None else None,
                        right=bbox[2] if bbox is not None else None,
                        bottom=bbox[3] if bbox is not None else None,
                    )
                )
            except ValueError:
                continue
        return spans

    @staticmethod
    def _convert_artifact(artifact: MinerUArtifact, *, source_stem: str) -> UploadFilePayload:
        if artifact.artifact_type == "markdown":
            return UploadFilePayload(
                filename=f"{source_stem}.mineru.md",
                content=artifact.content,
                content_type=artifact.content_type,
            )
        if artifact.artifact_type == "layout":
            return UploadFilePayload(
                filename=f"{source_stem}.mineru.layout.json",
                content=artifact.content,
                content_type=artifact.content_type,
            )
        if artifact.artifact_type == "content_list":
            return UploadFilePayload(
                filename=f"{source_stem}.mineru.content_list.json",
                content=artifact.content,
                content_type=artifact.content_type,
            )
        return UploadFilePayload(
            filename=artifact.filename,
            content=artifact.content,
            content_type=artifact.content_type
            or MinerUService._guess_content_type(artifact.filename),
            relative_path=artifact.relative_path,
            root_directory=f"{source_stem}.mineru.assets",
        )

    @staticmethod
    def _guess_content_type(filename: str) -> str:
        guessed, _ = mimetypes.guess_type(filename)
        return guessed or "application/octet-stream"


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    normalized = value.strip()
    return normalized or None


def _extract_content_text(item: Mapping[str, Any]) -> str | None:
    for key in _TEXT_KEYS:
        value = item.get(key)
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return normalized
    return None


def _extract_page_number(item: Mapping[str, Any]) -> int | None:
    for key in _PAGE_ONE_BASED_KEYS:
        value = _to_int(item.get(key))
        if value is not None and value > 0:
            return value
    for key in _PAGE_ZERO_BASED_KEYS:
        value = _to_int(item.get(key))
        if value is not None and value >= 0:
            return value + 1
    return None


def _extract_bbox(item: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    for key in _BBOX_KEYS:
        bbox = _coerce_bbox(item.get(key))
        if bbox is not None:
            return bbox
    return None


def _coerce_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, Mapping):
        left = _to_float(_first_value(value, "left", "x0", "x_min", "xmin"))
        top = _to_float(_first_value(value, "top", "y0", "y_min", "ymin"))
        right = _to_float(_first_value(value, "right", "x1", "x_max", "xmax"))
        bottom = _to_float(_first_value(value, "bottom", "y1", "y_max", "ymax"))
        if left is not None and top is not None and right is not None and bottom is not None:
            return (left, top, right, bottom)
    if isinstance(value, list | tuple) and len(value) >= 4:
        numbers = [_to_float(item) for item in value[:4]]
        left, top, right, bottom = numbers
        if left is not None and top is not None and right is not None and bottom is not None:
            return (left, top, right, bottom)
    return None


def _normalize_bbox(
    bbox: tuple[float, float, float, float] | None,
    page_size: tuple[float, float] | None,
) -> tuple[float, float, float, float] | None:
    if bbox is None:
        return None
    left, top, right, bottom = bbox
    left, right = sorted((left, right))
    top, bottom = sorted((top, bottom))
    if all(0 <= item <= 1 for item in (left, top, right, bottom)):
        return (left, top, right, bottom)
    if page_size is None:
        return None
    width, height = page_size
    if width <= 0 or height <= 0:
        return None
    normalized = (left / width, top / height, right / width, bottom / height)
    if all(0 <= item <= 1 for item in normalized):
        return normalized
    return None


def _collect_page_sizes(value: Any) -> dict[int, tuple[float, float]]:
    sizes: dict[int, tuple[float, float]] = {}

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            page = _extract_page_number(item)
            width = _to_float(_first_value(item, *_WIDTH_KEYS))
            height = _to_float(_first_value(item, *_HEIGHT_KEYS))
            if page is not None and width is not None and height is not None:
                sizes.setdefault(page, (width, height))
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return sizes


def _first_value(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item:
            return item[key]
    return None


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None
