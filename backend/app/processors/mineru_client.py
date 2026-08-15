"""本地 MinerU `/file_parse` 的轻量异步客户端。"""

from __future__ import annotations

import json
import mimetypes
import shutil
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from cogmait_shared.files import TempFileStore

from ..core.config import settings

__all__ = [
    "MinerUArtifact",
    "MinerUClient",
    "MinerUClientError",
    "MinerUFileConfig",
    "MinerUProcessingResult",
]

_SUPPORTED_FILE_SUFFIXES = frozenset({".pdf", ".docx", ".doc"})
_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})


class MinerUClientError(Exception):
    """MinerU 调用或结果解析失败。"""


@dataclass(slots=True)
class MinerUFileConfig:
    """待提交给 MinerU 的本地文件配置。"""

    name: str
    path: Path


@dataclass(slots=True)
class MinerUArtifact:
    """MinerU 解析产物的内存表示。"""

    artifact_type: str
    filename: str
    content: bytes
    content_type: str
    relative_path: str | None = None


@dataclass(slots=True)
class MinerUProcessingResult:
    """MinerU 本地解析后的标准化结果。"""

    success: bool
    content: str
    output_dir: str | None = None
    output_files: list[str] = field(default_factory=list)
    artifacts: list[MinerUArtifact] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class MinerUClient:
    """封装本地 MinerU `/file_parse` 调用。"""

    def __init__(
        self,
        *,
        local_api_base: str | None = None,
        local_backend: str | None = None,
        local_timeout: float | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if local_api_base is not None and not isinstance(local_api_base, str):
            raise MinerUClientError("local_api_base 必须为字符串")
        if local_backend is not None and not isinstance(local_backend, str):
            raise MinerUClientError("local_backend 必须为字符串")
        if local_timeout is not None and (
            isinstance(local_timeout, bool) or not isinstance(local_timeout, int | float)
        ):
            raise MinerUClientError("timeout 必须为数字")

        resolved_local_api_base = self._normalize_optional_text(
            local_api_base if local_api_base is not None else settings.mineru_local_api_base,
            field_name="local_api_base",
        )
        if resolved_local_api_base is None:
            raise MinerUClientError("必须显式传入 local_api_base 或配置 MINERU_LOCAL_API_BASE")

        resolved_local_backend = self._normalize_optional_text(
            local_backend if local_backend is not None else settings.mineru_local_backend,
            field_name="local_backend",
        )
        if resolved_local_backend is None:
            raise MinerUClientError("local_backend 不能为空")

        resolved_timeout = self._resolve_timeout(
            local_timeout if local_timeout is not None else settings.mineru_local_timeout
        )

        self.local_api_base = resolved_local_api_base.rstrip("/")
        self.local_backend = resolved_local_backend
        self.local_timeout = resolved_timeout
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.local_api_base,
            timeout=resolved_timeout,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def process_file_to_markdown(
        self,
        file_path: str,
        *,
        output_dir: str | Path | None = None,
        language: str | None = None,
        cleanup_local_output: bool = True,
    ) -> MinerUProcessingResult:
        """
        调用本地 MinerU 解析文件并返回 markdown 结果。

        Args:
            file_path: 本地待解析文件路径，仅支持 pdf/docx/doc。
            output_dir: 解析产物输出目录；为空时自动创建临时目录。
            language: 传给 MinerU 的语言参数。
            cleanup_local_output: 是否在返回前清理本地产物目录。
                - True：默认行为。返回值中的文件内容会先读入内存，再删除本地目录。
                - False：保留 output_dir，供调用方继续读取本地文件。
        """
        config = self._build_file_config(file_path)
        extract_dir = self._ensure_output_dir(output_dir)
        try:
            zip_path = extract_dir / "mineru_result.zip"
            zip_bytes = await self._request_local_parse_zip(config=config, language=language)
            zip_path.write_bytes(zip_bytes)
            return self._build_processing_result_from_zip(
                zip_path=zip_path,
                extract_dir=extract_dir,
                cleanup_local_output=cleanup_local_output,
            )
        finally:
            if cleanup_local_output and extract_dir.exists():
                shutil.rmtree(extract_dir, ignore_errors=True)

    async def _request_local_parse_zip(
        self,
        *,
        config: MinerUFileConfig,
        language: str | None,
    ) -> bytes:
        data: list[tuple[str, str]] = [
            ("backend", self.local_backend),
            ("parse_method", "auto"),
            ("return_md", "true"),
            ("return_middle_json", "true"),
            ("return_content_list", "true"),
            ("response_format_zip", "true"),
        ]
        normalized_language = self._normalize_optional_text(language, field_name="language")
        if normalized_language is not None:
            data.append(("lang_list", normalized_language))

        boundary = f"mineru-boundary-{uuid.uuid4().hex}"
        response = await self._client.request(
            "POST",
            "/file_parse",
            content=self._build_multipart_form_data(
                boundary=boundary,
                fields=data,
                file_field="files",
                file_name=config.name,
                file_content=config.path.read_bytes(),
                file_content_type=self._guess_content_type(config.path),
            ),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise MinerUClientError(
                f"MinerU 请求失败：{self._extract_error_message(response)}"
            ) from exc

        content_type = str(response.headers.get("content-type") or "").lower()
        if "zip" not in content_type:
            raise MinerUClientError(
                f"MinerU 返回内容不是 zip：{self._extract_error_message(response)}"
            )
        return response.content

    def _build_processing_result_from_zip(
        self,
        *,
        zip_path: Path,
        extract_dir: Path,
        cleanup_local_output: bool,
    ) -> MinerUProcessingResult:
        with zipfile.ZipFile(zip_path, "r") as archive:
            self._safe_extract_zip(archive, target_dir=extract_dir)

        output_files = sorted(
            str(path)
            for path in extract_dir.rglob("*")
            if path.is_file() and path.resolve() != zip_path.resolve()
        )
        markdown_files = sorted(path for path in extract_dir.rglob("*.md") if path.is_file())
        if not markdown_files:
            raise MinerUClientError("MinerU 结果中缺少 markdown 文件")

        primary_markdown_path = markdown_files[0]
        layout_path = self._find_first_result_file(
            extract_dir,
            patterns=("*_middle.json", "layout.json"),
        )
        content_list_path = self._find_first_result_file(
            extract_dir,
            patterns=("*_content_list.json", "content_list.json"),
        )
        artifacts = self._build_artifacts(
            extract_dir=extract_dir,
            markdown_path=primary_markdown_path,
            layout_path=layout_path,
            content_list_path=content_list_path,
        )

        metadata: dict[str, Any] = {
            "image_filenames": [
                artifact.filename for artifact in artifacts if artifact.artifact_type == "image"
            ],
        }
        if not cleanup_local_output:
            metadata["primary_markdown_path"] = str(primary_markdown_path)
            metadata["image_paths"] = [
                path for path in output_files if Path(path).suffix.lower() in _IMAGE_SUFFIXES
            ]
        if layout_path is not None:
            if not cleanup_local_output:
                metadata["layout_path"] = str(layout_path)
            layout = self._load_json_file(layout_path)
            if isinstance(layout, dict):
                metadata["layout"] = layout
        if content_list_path is not None:
            if not cleanup_local_output:
                metadata["content_list_path"] = str(content_list_path)
            content_list = self._load_json_file(content_list_path)
            if isinstance(content_list, list):
                metadata["content_list"] = content_list

        return MinerUProcessingResult(
            success=True,
            content=primary_markdown_path.read_text(encoding="utf-8"),
            output_dir=None if cleanup_local_output else str(extract_dir),
            output_files=[] if cleanup_local_output else output_files,
            artifacts=artifacts,
            metadata=metadata,
        )

    @staticmethod
    def _build_artifacts(
        *,
        extract_dir: Path,
        markdown_path: Path,
        layout_path: Path | None,
        content_list_path: Path | None,
    ) -> list[MinerUArtifact]:
        artifacts = [
            MinerUArtifact(
                artifact_type="markdown",
                filename=markdown_path.name,
                content=markdown_path.read_bytes(),
                content_type="text/markdown",
            )
        ]
        if layout_path is not None and layout_path.is_file():
            artifacts.append(
                MinerUArtifact(
                    artifact_type="layout",
                    filename=layout_path.name,
                    content=layout_path.read_bytes(),
                    content_type="application/json",
                    relative_path=MinerUClient._build_relative_path(extract_dir, layout_path),
                )
            )
        if content_list_path is not None and content_list_path.is_file():
            artifacts.append(
                MinerUArtifact(
                    artifact_type="content_list",
                    filename=content_list_path.name,
                    content=content_list_path.read_bytes(),
                    content_type="application/json",
                    relative_path=MinerUClient._build_relative_path(extract_dir, content_list_path),
                )
            )
        for image_path in sorted(
            path for path in extract_dir.rglob("*") if path.suffix.lower() in _IMAGE_SUFFIXES
        ):
            artifacts.append(
                MinerUArtifact(
                    artifact_type="image",
                    filename=image_path.name,
                    content=image_path.read_bytes(),
                    content_type=MinerUClient._guess_content_type(image_path),
                    relative_path=MinerUClient._build_relative_path(extract_dir, image_path),
                )
            )
        return artifacts

    @staticmethod
    def _build_relative_path(root_dir: Path, path: Path) -> str | None:
        try:
            relative = path.relative_to(root_dir)
        except ValueError:
            return None
        if relative.parent == Path("."):
            return None
        return str(relative.parent)

    @staticmethod
    def _build_file_config(file_path: str) -> MinerUFileConfig:
        normalized_path = MinerUClient._normalize_optional_text(file_path, field_name="file_path")
        if normalized_path is None:
            raise MinerUClientError("file_path 不能为空")

        path = Path(normalized_path)
        if not path.exists():
            raise MinerUClientError(f"文件不存在：{normalized_path}")
        if not path.is_file():
            raise MinerUClientError(f"文件路径不是文件：{normalized_path}")
        if path.suffix.lower() not in _SUPPORTED_FILE_SUFFIXES:
            raise MinerUClientError("MinerU 仅支持 pdf、docx、doc 文件")

        return MinerUFileConfig(name=path.name, path=path)

    @staticmethod
    def _ensure_output_dir(output_dir: str | Path | None) -> Path:
        if output_dir is None or (isinstance(output_dir, str) and not output_dir.strip()):
            return TempFileStore().create_dir(prefix="mineru-output-", subdir="mineru")
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _resolve_timeout(raw_timeout: Any) -> float:
        if isinstance(raw_timeout, bool):
            raise MinerUClientError("timeout 必须为数字")
        try:
            resolved_timeout = float(raw_timeout)
        except (TypeError, ValueError) as exc:
            raise MinerUClientError("timeout 必须为数字") from exc
        if resolved_timeout <= 0:
            raise MinerUClientError("timeout 必须大于 0")
        return resolved_timeout

    @staticmethod
    def _normalize_optional_text(value: Any, *, field_name: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise MinerUClientError(f"{field_name} 提供时必须为字符串")
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            text = response.text.strip()
            return text or f"HTTP {response.status_code}"

        if isinstance(payload, dict):
            for key in ("detail", "message", "error", "msg"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return f"HTTP {response.status_code}"

    @staticmethod
    def _guess_content_type(path: Path) -> str:
        guessed, _ = mimetypes.guess_type(path.name)
        return guessed or "application/octet-stream"

    @staticmethod
    def _build_multipart_form_data(
        *,
        boundary: str,
        fields: list[tuple[str, str]],
        file_field: str,
        file_name: str,
        file_content: bytes,
        file_content_type: str,
    ) -> bytes:
        body = bytearray()

        def _append_text_part(name: str, value: str) -> None:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.extend(value.encode("utf-8"))
            body.extend(b"\r\n")

        for name, value in fields:
            _append_text_part(name, value)

        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_name}"\r\n'
            ).encode()
        )
        body.extend(f"Content-Type: {file_content_type}\r\n\r\n".encode())
        body.extend(file_content)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())
        return bytes(body)

    @staticmethod
    def _safe_extract_zip(archive: zipfile.ZipFile, *, target_dir: Path) -> None:
        target_dir = target_dir.resolve()
        for member in archive.infolist():
            member_path = (target_dir / member.filename).resolve()
            if member_path != target_dir and target_dir not in member_path.parents:
                raise MinerUClientError("Unsafe zip entry path")
        archive.extractall(target_dir)

    @staticmethod
    def _find_result_file(extract_dir: Path, pattern: str) -> Path | None:
        matches = sorted(path for path in extract_dir.rglob(pattern) if path.is_file())
        return matches[0] if matches else None

    @classmethod
    def _find_first_result_file(
        cls,
        extract_dir: Path,
        *,
        patterns: tuple[str, ...],
    ) -> Path | None:
        for pattern in patterns:
            match = cls._find_result_file(extract_dir, pattern)
            if match is not None:
                return match
        return None

    @staticmethod
    def _load_json_file(path: Path) -> Any | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
