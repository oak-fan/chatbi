"""RapidOCR 内容提取适配器。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cogmait_shared.files import FileRecord
from cogmait_shared.observability.logging import logger

from ....core.config import settings
from ....domain.system import ContentExtractLocatorSpan, ContentExtractProvider
from ....processors import RapidOCRClient, RapidOCRError, RapidOCRParseResult

__all__ = ["RapidOCRService", "RapidOCRServiceError"]


class RapidOCRServiceError(Exception):
    """RapidOCR 服务调用失败。"""


@dataclass(slots=True)
class RapidOCRExtractResult:
    """RapidOCR 标准化后的提取结果。"""

    success: bool
    source_file_id: int
    source_file_name: str
    provider_used: ContentExtractProvider
    content_text: str
    metadata: dict[str, object]
    locator_spans: list[ContentExtractLocatorSpan]


class RapidOCRService:
    """负责本地 RapidOCR 调用与文本组装。"""

    provider = ContentExtractProvider.RAPIDOCR

    def __init__(
        self,
        *,
        rapidocr_client: RapidOCRClient | None = None,
    ) -> None:
        self._rapidocr_client = rapidocr_client

    def is_available(self) -> bool:
        if self._rapidocr_client is not None:
            return True
        return bool(_normalize_optional_text(settings.rapidocr_api_base))

    @staticmethod
    def supports_file(file_record: FileRecord) -> bool:
        return file_record.file_extension.lower().removeprefix(".") == "pdf"

    async def extract_from_local_file(
        self,
        *,
        source_file_id: int,
        source_file_name: str,
        local_file_path: Path,
        work_dir: Path,
        force_ocr: bool | None = None,
        page_num_list: list[int] | None = None,
    ) -> RapidOCRExtractResult:
        """基于本地文件执行 RapidOCR 提取。"""
        try:
            self._ensure_pdf(source_file_name)
            work_dir.mkdir(parents=True, exist_ok=True)
            parse_result = await self._get_client().parse_pdf(
                file_path=local_file_path.as_posix(),
                force_ocr=force_ocr,
                page_num_list=page_num_list,
            )
            content_text, locator_spans = self._build_markdown_and_locator_spans(parse_result)
            return RapidOCRExtractResult(
                success=True,
                source_file_id=source_file_id,
                source_file_name=source_file_name,
                provider_used=self.provider,
                content_text=content_text,
                metadata=self._build_metadata(
                    source_file_name=source_file_name,
                    parse_result=parse_result,
                ),
                locator_spans=locator_spans,
            )
        except RapidOCRError as exc:
            raise RapidOCRServiceError(str(exc)) from exc
        except Exception as exc:
            logger.opt(exception=exc).error("RapidOCR 解析失败")
            raise RapidOCRServiceError(f"RapidOCR 解析失败：{exc}") from exc

    @staticmethod
    def _ensure_pdf(source_file_name: str) -> None:
        if Path(source_file_name).suffix.lower() != ".pdf":
            raise RapidOCRServiceError("RapidOCR 仅支持 pdf 文件")

    @staticmethod
    def _build_markdown_and_locator_spans(
        parse_result: RapidOCRParseResult,
    ) -> tuple[str, list[ContentExtractLocatorSpan]]:
        pages = sorted(parse_result.pages, key=lambda item: item.page_index)
        texts = [page.text.strip() for page in pages if page.text.strip()]
        if not texts:
            return "", []
        if len(pages) == 1:
            content = texts[0]
            return content, [
                ContentExtractLocatorSpan(
                    start=0,
                    end=len(content),
                    page=pages[0].page_index + 1,
                )
            ]

        content_parts: list[str] = []
        locator_spans: list[ContentExtractLocatorSpan] = []
        offset = 0
        for page in pages:
            page_text = page.text.strip()
            if not page_text:
                continue
            if content_parts:
                content_parts.append("\n\n")
                offset += 2
            prefix = f"## Page {page.page_index + 1}\n\n"
            content_parts.append(prefix)
            offset += len(prefix)
            start = offset
            content_parts.append(page_text)
            offset += len(page_text)
            locator_spans.append(
                ContentExtractLocatorSpan(
                    start=start,
                    end=offset,
                    page=page.page_index + 1,
                )
            )
        return "".join(content_parts), locator_spans

    @staticmethod
    def _build_metadata(
        *,
        source_file_name: str,
        parse_result: RapidOCRParseResult,
    ) -> dict[str, object]:
        return {
            "source_file_extension": Path(source_file_name).suffix.removeprefix(".").lower(),
            "page_count": len(parse_result.pages),
            "page_indexes": [page.page_index for page in parse_result.pages],
        }

    def _get_client(self) -> RapidOCRClient:
        if self._rapidocr_client is None:
            self._rapidocr_client = RapidOCRClient()
        return self._rapidocr_client


def _normalize_optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
