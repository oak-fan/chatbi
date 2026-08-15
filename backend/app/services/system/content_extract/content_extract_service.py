"""统一内容提取服务。"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cogmait_shared.clients.contracts.main_api import UploadFilePayload
from cogmait_shared.core.id_generator import generate_snowflake_id
from cogmait_shared.files import FileBusinessType, FileRecord
from cogmait_shared.observability.logging import logger

from ....core.config import PROJECT_ROOT
from ....domain.system import (
    ContentExtractLocatorSpan,
    ContentExtractMode,
    ContentExtractProvider,
    ContentExtractRequest,
    ContentExtractResult,
)
from .file_access_service import DownloadedFile, FileAccessService, FileAccessServiceError
from .mineru_service import MinerUService, MinerUServiceError
from .rapidocr_service import RapidOCRService, RapidOCRServiceError

__all__ = ["ContentExtractService", "ContentExtractServiceError"]

_DEFAULT_SAVE_RETRY_TIMES = 3
_TMP_ROOT = PROJECT_ROOT / "tmp" / "content_extract"
_PDF_EXTENSIONS = frozenset({"pdf"})
_WORD_EXTENSIONS = frozenset({"doc", "docx"})


class ContentExtractServiceError(Exception):
    """统一内容提取服务失败。"""


@dataclass(slots=True)
class _TaskDirectories:
    task_id: str
    task_dir: Path
    source_dir: Path
    work_dir: Path
    result_dir: Path

    def create(self) -> None:
        self.source_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.result_dir.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class _ExtractedContent:
    content_text: str
    locator_spans: list[ContentExtractLocatorSpan]


class ContentExtractService:
    """按模式自动选择内部提取器，输出统一文本结果。"""

    def __init__(
        self,
        *,
        file_access_service: FileAccessService | None = None,
        mineru_service: MinerUService | None = None,
        rapidocr_service: RapidOCRService | None = None,
        task_id_factory: Callable[[], int | str] | None = None,
    ) -> None:
        self._file_access_service = file_access_service or FileAccessService()
        self._mineru_service = mineru_service or MinerUService()
        self._rapidocr_service = rapidocr_service or RapidOCRService()
        self._task_id_factory = task_id_factory or generate_snowflake_id
        self._extractors: dict[ContentExtractProvider, MinerUService | RapidOCRService] = {
            ContentExtractProvider.MINERU: self._mineru_service,
            ContentExtractProvider.RAPIDOCR: self._rapidocr_service,
        }

    async def extract_content(
        self,
        request: ContentExtractRequest,
    ) -> ContentExtractResult:
        """统一提取文件正文内容，并在需要时保存主结果 markdown。"""
        task_dirs = self._create_task_directories()
        task_dirs.create()

        try:
            downloaded_file = await self._file_access_service.download_file(
                request.file_id,
                target_dir=task_dirs.source_dir,
            )
            provider = self._resolve_provider(
                file_record=downloaded_file.file_record,
                mode=request.mode,
            )
            extracted = await self._extract_with_provider(
                provider=provider,
                downloaded_file=downloaded_file,
                work_dir=task_dirs.work_dir,
                request=request,
            )

            saved_file_id = None
            if request.save_result:
                saved_file_id = await self._save_result(
                    file_record=downloaded_file.file_record,
                    content_text=extracted.content_text,
                    result_dir=task_dirs.result_dir,
                    request=request,
                )

            return ContentExtractResult(
                success=True,
                source_file_id=downloaded_file.file_id,
                source_file_name=downloaded_file.file_record.original_name,
                provider_used=provider,
                content_text=extracted.content_text,
                saved_file_id=saved_file_id,
                locator_spans=extracted.locator_spans,
            )
        except (FileAccessServiceError, MinerUServiceError, RapidOCRServiceError) as exc:
            raise ContentExtractServiceError(str(exc)) from exc
        except ContentExtractServiceError:
            raise
        except Exception as exc:
            logger.opt(exception=exc).error("统一内容提取失败")
            raise ContentExtractServiceError(f"统一内容提取失败：{exc}") from exc
        finally:
            shutil.rmtree(task_dirs.task_dir, ignore_errors=True)

    def _resolve_provider(
        self,
        *,
        file_record: FileRecord,
        mode: ContentExtractMode,
    ) -> ContentExtractProvider:
        file_extension = self._normalize_file_extension(file_record.file_extension)

        if file_extension in _WORD_EXTENSIONS:
            return self._resolve_first_available(
                file_record=file_record,
                candidates=[ContentExtractProvider.MINERU],
            )
        if file_extension in _PDF_EXTENSIONS:
            if mode == ContentExtractMode.FAST and self._is_provider_usable(
                provider=ContentExtractProvider.RAPIDOCR,
                file_record=file_record,
            ):
                return ContentExtractProvider.RAPIDOCR
            return self._resolve_first_available(
                file_record=file_record,
                candidates=[
                    ContentExtractProvider.MINERU,
                    ContentExtractProvider.RAPIDOCR,
                ],
            )

        raise ContentExtractServiceError(f"暂不支持该文件类型：{file_extension or 'unknown'}")

    def _resolve_first_available(
        self,
        *,
        file_record: FileRecord,
        candidates: list[ContentExtractProvider],
    ) -> ContentExtractProvider:
        for provider in candidates:
            if self._is_provider_usable(provider=provider, file_record=file_record):
                return provider

        provider_names = ", ".join(item.value for item in candidates)
        logger.error(
            "内容提取器不可用",
            extra={
                "file_id": file_record.id,
                "file_name": file_record.original_name,
                "file_extension": file_record.file_extension,
                "candidate_providers": provider_names,
            },
        )
        raise ContentExtractServiceError(f"当前环境没有可用的内容提取器：{provider_names}")

    def _is_provider_usable(
        self,
        *,
        provider: ContentExtractProvider,
        file_record: FileRecord,
    ) -> bool:
        extractor = self._extractors[provider]
        return extractor.is_available() and extractor.supports_file(file_record)

    async def _extract_with_provider(
        self,
        *,
        provider: ContentExtractProvider,
        downloaded_file: DownloadedFile,
        work_dir: Path,
        request: ContentExtractRequest,
    ) -> _ExtractedContent:
        if provider == ContentExtractProvider.MINERU:
            try:
                result = await self._mineru_service.extract_from_local_file(
                    source_file_id=downloaded_file.file_id,
                    source_file_name=downloaded_file.file_record.original_name,
                    local_file_path=downloaded_file.local_path,
                    work_dir=work_dir,
                    language=request.mineru_options.language if request.mineru_options else None,
                )
                return _ExtractedContent(
                    content_text=result.content_text,
                    locator_spans=list(getattr(result, "locator_spans", [])),
                )
            except MinerUServiceError as exc:
                logger.opt(exception=exc).error(
                    "MinerU 内容提取失败",
                    extra={
                        "file_id": downloaded_file.file_id,
                        "file_name": downloaded_file.file_record.original_name,
                        "file_extension": downloaded_file.file_record.file_extension,
                    },
                )
                raise

        rapidocr_result = await self._rapidocr_service.extract_from_local_file(
            source_file_id=downloaded_file.file_id,
            source_file_name=downloaded_file.file_record.original_name,
            local_file_path=downloaded_file.local_path,
            work_dir=work_dir,
            force_ocr=request.rapidocr_options.force_ocr if request.rapidocr_options else None,
            page_num_list=(
                list(request.rapidocr_options.page_num_list)
                if request.rapidocr_options and request.rapidocr_options.page_num_list is not None
                else None
            ),
        )
        return _ExtractedContent(
            content_text=rapidocr_result.content_text,
            locator_spans=list(getattr(rapidocr_result, "locator_spans", [])),
        )

    async def _save_result(
        self,
        *,
        file_record: FileRecord,
        content_text: str,
        result_dir: Path,
        request: ContentExtractRequest,
    ) -> int:
        result_path = result_dir / self._build_result_filename(file_record.original_name)
        result_path.write_text(content_text, encoding="utf-8")
        upload_payload = [
            UploadFilePayload(
                filename=result_path.name,
                content=result_path.read_bytes(),
                content_type="text/markdown",
            )
        ]

        last_error: Exception | None = None
        for _ in range(_DEFAULT_SAVE_RETRY_TIMES):
            try:
                upload_results = await self._file_access_service.upload_files(
                    upload_payload,
                    business_type=FileBusinessType.AGENT_OUTPUT,
                    is_temporary=request.save_result_is_temporary,
                    ttl_seconds=request.save_result_ttl_seconds,
                    operator_id=request.operator_id,
                )
                if not upload_results:
                    raise ContentExtractServiceError("保存提取结果失败：文件服务未返回文件记录")
                return upload_results[0].record.id
            except (FileAccessServiceError, ContentExtractServiceError) as exc:
                last_error = exc

        if last_error is None:
            raise ContentExtractServiceError("保存提取结果失败")
        raise ContentExtractServiceError(str(last_error)) from last_error

    def _create_task_directories(self) -> _TaskDirectories:
        task_id = str(self._task_id_factory())
        task_dir = _TMP_ROOT / task_id
        return _TaskDirectories(
            task_id=task_id,
            task_dir=task_dir,
            source_dir=task_dir / "source",
            work_dir=task_dir / "work",
            result_dir=task_dir / "result",
        )

    @staticmethod
    def _normalize_file_extension(file_extension: str | None) -> str:
        normalized = str(file_extension or "").strip().lower()
        return normalized.removeprefix(".")

    @staticmethod
    def _build_result_filename(original_name: str) -> str:
        stem = Path(original_name).stem or "document"
        return f"{stem}.extracted.md"
