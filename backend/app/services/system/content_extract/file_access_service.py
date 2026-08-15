"""通过 main_api 文件服务读取源文件。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from cogmait_shared.clients.contracts.main_api import (
    FileClientError,
    InternalFileClient,
    UploadFilePayload,
)
from cogmait_shared.files import FileBusinessType, FileRecord, FileUploadResult, TempFileStore

__all__ = ["DownloadedFile", "FileAccessService", "FileAccessServiceError"]


class FileAccessServiceError(Exception):
    """文件访问失败。"""


@dataclass(slots=True)
class DownloadedFile:
    """从文件服务下载到本地的源文件。"""

    file_id: int
    file_record: FileRecord
    local_path: Path


class FileAccessService:
    """复用 main_api 文件服务客户端下载源文件。"""

    def __init__(
        self,
        *,
        file_client: InternalFileClient | None = None,
        download_timeout: float = 60.0,
    ) -> None:
        self._file_client = file_client or InternalFileClient()
        self._download_timeout = float(download_timeout)

    async def aclose(self) -> None:
        """释放内部文件客户端持有的 HTTP 连接。"""
        await self._file_client.aclose()

    async def __aenter__(self) -> FileAccessService:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def get_file(self, file_id: int) -> FileRecord:
        try:
            return await self._file_client.get(file_id)
        except (FileClientError, ValueError) as exc:
            raise FileAccessServiceError(f"获取文件失败：{exc}") from exc

    async def list_files(self, file_ids: Sequence[int]) -> list[FileRecord]:
        try:
            return await self._file_client.batch_query(file_ids)
        except (FileClientError, ValueError) as exc:
            raise FileAccessServiceError(f"批量获取文件失败：{exc}") from exc

    async def search_files(
        self,
        *,
        file_ids: Sequence[int] | None = None,
        keyword: str | None = None,
        business_code: FileBusinessType | str | None = None,
        is_temporary: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[FileRecord], int]:
        try:
            return await self._file_client.search_files(
                file_ids=file_ids,
                keyword=keyword,
                business_code=business_code,
                is_temporary=is_temporary,
                page=page,
                size=size,
            )
        except (FileClientError, ValueError) as exc:
            raise FileAccessServiceError(f"分页获取文件失败：{exc}") from exc

    async def download_file(self, file_id: int, *, target_dir: Path) -> DownloadedFile:
        try:
            file_record = await self.get_file(file_id)
            presigned = await self._file_client.presign_download(file_id)
        except (FileClientError, ValueError) as exc:
            raise FileAccessServiceError(f"获取文件失败：{exc}") from exc

        temp_store = TempFileStore(base_dir=target_dir)
        local_path = temp_store.build_file_path(
            filename=self._build_local_source_name(
                file_id=file_record.id,
                original_name=file_record.original_name,
            )
        )
        try:
            async with httpx.AsyncClient(
                timeout=self._download_timeout,
                follow_redirects=True,
            ) as client:
                async with client.stream("GET", presigned.url) as response:
                    response.raise_for_status()
                    with local_path.open("wb") as file_obj:
                        async for chunk in response.aiter_bytes():
                            if chunk:
                                file_obj.write(chunk)
        except (httpx.HTTPError, OSError) as exc:
            raise FileAccessServiceError(f"下载文件失败：{exc}") from exc

        return DownloadedFile(
            file_id=file_record.id,
            file_record=file_record,
            local_path=local_path,
        )

    async def upload_files(
        self,
        files: Sequence[UploadFilePayload],
        *,
        business_type: FileBusinessType = FileBusinessType.AGENT_OUTPUT,
        is_temporary: bool = False,
        ttl_seconds: int | None = None,
        root_directory: str | None = None,
        operator_id: int | None = None,
    ) -> list[FileUploadResult]:
        normalized_files = self._apply_root_directory(files, root_directory=root_directory)
        try:
            return await self._file_client.upload(
                normalized_files,
                business_code=business_type,
                is_temporary=is_temporary,
                ttl_seconds=ttl_seconds,
                operator_id=operator_id,
            )
        except (FileClientError, ValueError) as exc:
            raise FileAccessServiceError(f"上传文件失败：{exc}") from exc

    async def delete_file(
        self,
        file_id: int,
    ) -> bool:
        try:
            deleted_count = await self._file_client.delete_files([file_id])
        except (FileClientError, ValueError) as exc:
            raise FileAccessServiceError(f"删除文件失败：{exc}") from exc
        return deleted_count > 0

    async def mark_files_temporary(self, file_ids: Sequence[int]) -> int:
        try:
            return await self._file_client.mark_files_temporary(file_ids)
        except (FileClientError, ValueError) as exc:
            raise FileAccessServiceError(f"标记临时文件失败：{exc}") from exc

    @staticmethod
    def _build_local_source_name(*, file_id: int, original_name: str) -> str:
        suffix = Path(original_name).suffix or ".bin"
        return f"source-{file_id}{suffix}"

    @staticmethod
    def _apply_root_directory(
        files: Sequence[UploadFilePayload],
        *,
        root_directory: str | None,
    ) -> list[UploadFilePayload]:
        normalized_root = str(root_directory).strip() if root_directory is not None else None
        if not normalized_root:
            return list(files)

        return [
            UploadFilePayload(
                filename=file.filename,
                content=file.content,
                content_type=file.content_type,
                stream=file.stream,
                file_size=file.file_size,
                relative_path=file.relative_path,
                root_directory=normalized_root,
            )
            for file in files
        ]
