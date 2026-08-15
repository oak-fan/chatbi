"""RapidOCR `/parse` API 的轻量异步客户端（ai_service 内部使用）。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse

import httpx

from cogmait_shared.core.coercion import parse_strict_bool

from ..core.config import settings


@dataclass(slots=True)
class RapidOCRPageResult:
    """描述 RapidOCR 对单页 PDF 的解析结果。"""

    page_index: int
    text: str
    confidence: float | None = None


@dataclass(slots=True)
class RapidOCRParseResult:
    """RapidOCR `/parse` 接口的标准化结果。"""

    pages: list[RapidOCRPageResult]

    @property
    def combined_text(self) -> str:
        return "\n".join(page.text for page in sorted(self.pages, key=lambda item: item.page_index))


class RapidOCRError(Exception):
    """RapidOCR 调用过程中出现的错误。"""


class RapidOCRClient:
    """封装 RapidOCR `/parse` 端点的上传与结果解析。"""

    def __init__(
        self,
        *,
        api_base: str | None = None,
        timeout: float | None = None,
        client: httpx.AsyncClient | None = None,
        use_sync_client: bool = False,
    ) -> None:
        if api_base is not None and not isinstance(api_base, str):
            raise RapidOCRError("api_base 必须为字符串")
        if timeout is not None and (
            isinstance(timeout, bool) or not isinstance(timeout, int | float)
        ):
            raise RapidOCRError("timeout 必须为数字")

        normalized_base = self._normalize_optional_text(
            api_base if api_base is not None else settings.rapidocr_api_base,
            field_name="api_base",
        )
        if normalized_base is None:
            raise RapidOCRError("必须显式传入 api_base 或配置 RAPIDOCR_API_BASE")

        resolved_timeout = self._resolve_timeout(
            timeout if timeout is not None else settings.rapidocr_timeout
        )

        self.api_base = normalized_base.rstrip("/")
        self._timeout = resolved_timeout
        self._use_sync_client = bool(use_sync_client)
        self._async_client: httpx.AsyncClient | None = None
        self._owns_client = False

        if not self._use_sync_client:
            self._async_client = client or httpx.AsyncClient(
                base_url=self.api_base,
                timeout=resolved_timeout,
                transport=httpx.AsyncHTTPTransport(),
            )
            self._owns_client = client is None

    async def __aenter__(self) -> RapidOCRClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def parse_pdf(
        self,
        file_path: str | None = None,
        *,
        content: bytes | None = None,
        file_name: str | None = None,
        force_ocr: bool | str | None = None,
        page_num_list: Iterable[int] | None = None,
    ) -> RapidOCRParseResult:
        """调用 RapidOCR 解析 PDF，返回标准化结构。"""

        file_field, file_handle = await self._build_upload_file_field(
            file_path=file_path,
            content=content,
            file_name=file_name,
        )
        normalized_force_ocr = self._resolve_force_ocr(force_ocr)
        form_data = self._build_parse_form_data(
            force_ocr=normalized_force_ocr,
            page_num_list=page_num_list,
        )

        if self._use_sync_client:
            file_field, file_handle = self._materialize_sync_upload_file(
                file_field=file_field,
                file_handle=file_handle,
            )

        try:
            response = await self._request_parse_api(file_field=file_field, form_data=form_data)
        finally:
            self._close_file_handle(file_handle)

        return self._parse_response(response)

    async def aclose(self) -> None:
        if self._owns_client and self._async_client:
            await self._async_client.aclose()

    def _resolve_force_ocr(self, force_ocr: Any | None) -> bool:
        if force_ocr is None:
            default_value = settings.rapidocr_force_ocr_default
            if isinstance(default_value, bool):
                return default_value
            parsed_default = parse_strict_bool(default_value)
            if parsed_default is None:
                raise RapidOCRError("RAPIDOCR_FORCE_OCR_DEFAULT 必须为布尔值")
            return parsed_default
        if isinstance(force_ocr, bool):
            return force_ocr
        parsed = parse_strict_bool(force_ocr)
        if parsed is None:
            raise RapidOCRError("force_ocr 必须为布尔值")
        return parsed

    @staticmethod
    def _resolve_timeout(raw_timeout: Any) -> float:
        if isinstance(raw_timeout, bool):
            raise RapidOCRError("timeout 必须为数字")
        try:
            resolved_timeout = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise RapidOCRError("timeout 必须为数字") from exc
        if resolved_timeout <= 0:
            raise RapidOCRError("timeout 必须大于 0")
        return resolved_timeout

    def _parse_response(self, response: httpx.Response) -> RapidOCRParseResult:
        try:
            payload = response.json()
        except ValueError as exc:
            raise RapidOCRError("无法将 RapidOCR 响应解析为 JSON") from exc

        if not isinstance(payload, list):
            raise RapidOCRError("RapidOCR 响应格式异常")

        pages: list[RapidOCRPageResult] = []
        for item in payload:
            if not isinstance(item, list | tuple) or len(item) < 2:
                raise RapidOCRError("RapidOCR 响应中页面条目无效")

            page_index, text = item[0], item[1]
            raw_confidence = item[2] if len(item) > 2 else None
            if isinstance(page_index, bool) or not isinstance(page_index, int):
                raise RapidOCRError("RapidOCR 页面条目类型非法")
            if not isinstance(text, str):
                raise RapidOCRError("RapidOCR 页面条目类型非法")

            confidence = None
            if isinstance(raw_confidence, int | float) and not isinstance(raw_confidence, bool):
                confidence = float(raw_confidence)

            pages.append(
                RapidOCRPageResult(
                    page_index=page_index,
                    text=text,
                    confidence=confidence,
                )
            )

        return RapidOCRParseResult(pages=pages)

    async def _build_upload_file_field(
        self,
        *,
        file_path: str | None,
        content: bytes | None,
        file_name: str | None,
    ) -> tuple[tuple[str, bytes | BinaryIO, str], BinaryIO | None]:
        normalized_file_path = self._normalize_optional_text(file_path, field_name="file_path")
        if content is None and normalized_file_path is None:
            raise RapidOCRError("必须提供 file_path 或 content")
        if content is not None and normalized_file_path is not None:
            raise RapidOCRError("file_path 和 content 不能同时提供")

        if content is not None:
            return self._build_content_upload_field(content=content, file_name=file_name), None

        if normalized_file_path is None:
            raise RapidOCRError("必须提供 file_path 或 content")

        if normalized_file_path.startswith(("http://", "https://")):
            return await self._build_remote_upload_field(
                file_path=normalized_file_path,
                file_name=file_name,
            )

        return self._build_local_upload_field(
            file_path=normalized_file_path,
            file_name=file_name,
        )

    @staticmethod
    def _build_content_upload_field(
        *,
        content: bytes,
        file_name: str | None,
    ) -> tuple[str, bytes, str]:
        if not content:
            raise RapidOCRError("content 不能为空")

        upload_name = RapidOCRClient._normalize_upload_name(file_name, fallback="upload.pdf")
        return upload_name, content, "application/pdf"

    async def _build_remote_upload_field(
        self,
        *,
        file_path: str,
        file_name: str | None,
    ) -> tuple[tuple[str, bytes, str], None]:
        payload = await self._fetch_url_bytes(file_path)
        upload_name = self._normalize_upload_name(
            file_name,
            fallback=self._name_from_url(file_path),
        )
        return (upload_name, payload, "application/pdf"), None

    @staticmethod
    def _name_from_url(url: str) -> str:
        parsed = urlparse(url)
        name = Path(parsed.path).name
        return name or "remote.pdf"

    def _build_local_upload_field(
        self,
        *,
        file_path: str,
        file_name: str | None,
    ) -> tuple[tuple[str, BinaryIO, str], BinaryIO]:
        path = Path(file_path)
        if not path.exists():
            raise RapidOCRError(f"PDF 文件不存在：{file_path}")
        if not path.is_file():
            raise RapidOCRError(f"PDF 路径不是文件：{path}")

        file_handle = path.open("rb")
        upload_name = self._normalize_upload_name(file_name, fallback=path.name)
        return (upload_name, file_handle, "application/pdf"), file_handle

    @staticmethod
    def _build_parse_form_data(
        *,
        force_ocr: bool,
        page_num_list: Iterable[int] | None,
    ) -> list[tuple[str, str]]:
        form_data: list[tuple[str, str]] = [("force_ocr", "true" if force_ocr else "false")]
        if page_num_list is None:
            return form_data

        normalized_pages = RapidOCRClient._normalize_page_numbers(page_num_list)
        form_data.extend([("page_num_list", str(page)) for page in normalized_pages])
        return form_data

    @staticmethod
    def _normalize_page_numbers(page_num_list: Iterable[int]) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        for page in page_num_list:
            if isinstance(page, bool) or not isinstance(page, int) or page < 0:
                raise RapidOCRError("page_num_list 必须包含非负整数")
            if page in seen:
                continue
            seen.add(page)
            normalized.append(page)
        return normalized

    @staticmethod
    def _normalize_upload_name(file_name: str | None, *, fallback: str) -> str:
        normalized = RapidOCRClient._normalize_optional_text(file_name, field_name="file_name")
        if normalized is None:
            return fallback
        return normalized

    @staticmethod
    def _normalize_optional_text(value: Any, *, field_name: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise RapidOCRError(f"{field_name} 提供时必须为字符串")

        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _materialize_sync_upload_file(
        *,
        file_field: tuple[str, bytes | BinaryIO, str],
        file_handle: BinaryIO | None,
    ) -> tuple[tuple[str, bytes | BinaryIO, str], BinaryIO | None]:
        if file_handle is None:
            return file_field, file_handle

        try:
            file_bytes = file_handle.read()
        finally:
            file_handle.close()

        return (file_field[0], file_bytes, file_field[2]), None

    async def _request_parse_api(
        self,
        *,
        file_field: tuple[str, bytes | BinaryIO, str],
        form_data: list[tuple[str, str]],
    ) -> httpx.Response:
        try:
            response = await self._request(
                "POST",
                "/parse",
                data=form_data,
                files={"file": file_field},
            )
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise RapidOCRError(f"RapidOCR 请求失败：{exc}") from exc

    @staticmethod
    def _close_file_handle(file_handle: BinaryIO | None) -> None:
        if file_handle is not None:
            file_handle.close()

    async def _fetch_url_bytes(self, url: str) -> bytes:
        if self._use_sync_client:
            try:
                return await asyncio.to_thread(self._fetch_url_bytes_sync, url)
            except httpx.HTTPError as exc:
                raise RapidOCRError(f"从 URL 下载文件失败：{url}（{exc}）") from exc

        try:
            response = await self._request("GET", url)
            response.raise_for_status()
            return response.content
        except (RapidOCRError, httpx.HTTPError) as exc:
            raise RapidOCRError(f"从 URL 下载文件失败：{url}（{exc}）") from exc

    def _fetch_url_bytes_sync(self, url: str) -> bytes:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                with httpx.Client(
                    timeout=self._timeout,
                    headers={"Connection": "close"},
                ) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    return response.content
            except httpx.HTTPError as exc:
                last_error = exc
        if last_error is None:
            raise RapidOCRError(f"从 URL 下载文件失败：{url}（未知错误）")
        raise RapidOCRError(f"从 URL 下载文件失败：{url}（{last_error}）") from last_error

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        if self._use_sync_client:

            def _sync_request() -> httpx.Response:
                resolved_url = url if url.startswith("http") else f"{self.api_base}{url}"
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.request(method, resolved_url, **kwargs)
                return response

            return await asyncio.to_thread(_sync_request)

        if self._async_client is None:
            raise RapidOCRError("异步客户端未初始化")
        return await self._async_client.request(method, url, **kwargs)
