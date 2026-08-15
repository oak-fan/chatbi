"""文件客户端上传流程私有实现。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol, cast

from ....core.types import SnowflakeID
from ....files import FileUploadResult
from ....observability.logging import logger
from ...core import InternalAPICall, ServiceClientError
from .errors import FileClientError
from .file_client_parsers import (
    _ChunkPartUploadResult,
    _ChunkUploadInitResult,
    _parse_chunk_part_upload_result,
    _parse_chunk_upload_abort_result,
    _parse_chunk_upload_complete_result,
    _parse_chunk_upload_init_result,
)
from .file_upload_utils import build_upload_init_payload, iter_upload_chunks

__all__ = ["UploadFilePayload", "_UploadExecutionOptions", "_FileUploadMixin"]


class _UploadExecutor(Protocol):
    async def execute(self, call: InternalAPICall[Any], *, request_id: str | None = None) -> Any:
        """供上传混入类调用的执行接口。"""


@dataclass(slots=True)
class UploadFilePayload:
    """单文件上传载荷。"""

    filename: str
    content: bytes | None = None
    content_type: str | None = None
    stream: BinaryIO | None = None
    file_size: int | None = None
    relative_path: str | None = None
    root_directory: str | None = None


@dataclass(slots=True, frozen=True)
class _UploadExecutionOptions:
    """上传执行所需参数快照。"""

    business_value: str
    is_temporary: bool
    ttl_seconds: int | None
    operator_id: SnowflakeID | None
    operator_params: dict[str, Any] | None
    request_id: str | None


class _FileUploadMixin:
    """复用 InternalFileClient 的分块上传流程。"""

    _small_file_threshold_bytes: int

    async def execute(self, call: InternalAPICall[Any], *, request_id: str | None = None) -> Any:
        # 上传流程和普通查询都应复用真实的 HTTP 客户端实现。
        return await cast(_UploadExecutor, super()).execute(call, request_id=request_id)

    async def delete_files(
        self,
        file_ids: Sequence[SnowflakeID],
        *,
        hard_delete: bool = False,
        request_id: str | None = None,
    ) -> int:
        raise NotImplementedError

    async def _upload_single_file(
        self,
        *,
        file: UploadFilePayload,
        options: _UploadExecutionOptions,
        uploaded_results: list[FileUploadResult],
    ) -> None:
        upload_id: str | None = None
        try:
            file_size, init_payload = build_upload_init_payload(
                file=file,
                business_value=options.business_value,
                is_temporary=options.is_temporary,
                ttl_seconds=options.ttl_seconds,
                operator_id=options.operator_id,
                small_file_threshold_bytes=self._small_file_threshold_bytes,
            )
            init_result: _ChunkUploadInitResult = await self.execute(
                InternalAPICall(
                    method="POST",
                    path="/internal/v1/files/upload/init",
                    json=init_payload,
                    parser=_parse_chunk_upload_init_result,
                ),
                request_id=options.request_id,
            )
            upload_id = init_result.upload_id
            uploaded_parts = await self._upload_chunk_parts(
                upload_id=upload_id,
                file=file,
                file_size=file_size,
                part_size=init_result.part_size,
                operator_params=options.operator_params,
                request_id=options.request_id,
            )
            if uploaded_parts != init_result.total_parts:
                raise FileClientError("分块数量不匹配")
            upload_result = await self.execute(
                InternalAPICall(
                    method="POST",
                    path=f"/internal/v1/files/upload/{upload_id}/complete",
                    params=options.operator_params,
                    parser=_parse_chunk_upload_complete_result,
                ),
                request_id=options.request_id,
            )
            uploaded_results.append(upload_result)
        except (
            ServiceClientError,
            FileClientError,
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            normalized_exc = self._normalize_upload_exception(exc)
            await self._handle_upload_failure(
                exc=normalized_exc,
                upload_id=upload_id,
                options=options,
                uploaded_results=uploaded_results,
            )

    @staticmethod
    def _normalize_upload_exception(
        exc: ServiceClientError | FileClientError | OSError | TypeError | ValueError,
    ) -> ServiceClientError | FileClientError:
        if isinstance(exc, ServiceClientError | FileClientError):
            return exc
        return FileClientError(
            _FileUploadMixin._build_error_message(
                action="上传文件",
                detail="本地文件处理失败",
            )
        )

    async def _handle_upload_failure(
        self,
        *,
        exc: ServiceClientError | FileClientError,
        upload_id: str | None,
        options: _UploadExecutionOptions,
        uploaded_results: Sequence[FileUploadResult],
    ) -> None:
        if upload_id:
            await self._abort_chunk_upload_quietly(
                upload_id,
                operator_params=options.operator_params,
                request_id=options.request_id,
            )
        try:
            await self._cleanup_uploaded_results(
                uploaded_results,
                request_id=options.request_id,
            )
        except (ServiceClientError, FileClientError) as cleanup_exc:
            raise FileClientError(
                self._build_error_message(
                    action="上传文件",
                    detail=(
                        cleanup_exc.message
                        if isinstance(cleanup_exc, FileClientError)
                        else str(cleanup_exc)
                    ),
                    rollback_failed=True,
                ),
                status_code=cleanup_exc.status_code or exc.status_code,
            ) from cleanup_exc
        raise FileClientError(
            self._build_error_message(
                action="上传文件",
                detail=exc.message,
            ),
            status_code=exc.status_code,
        ) from exc

    async def _upload_chunk_parts(
        self,
        *,
        upload_id: str,
        file: UploadFilePayload,
        file_size: int,
        part_size: int,
        operator_params: dict[str, Any] | None,
        request_id: str | None,
    ) -> int:
        """按 part_size 逐片上传文件内容。"""
        part_number = 1
        for chunk_payload in iter_upload_chunks(
            file=file,
            file_size=file_size,
            part_size=part_size,
        ):
            result = await self.execute(
                self._build_chunk_part_call(
                    upload_id=upload_id,
                    part_number=part_number,
                    file=file,
                    chunk_payload=chunk_payload,
                    operator_params=operator_params,
                ),
                request_id=request_id,
            )
            self._validate_chunk_part_result(
                result,
                upload_id=upload_id,
                part_number=part_number,
            )
            part_number += 1
        return part_number - 1

    async def _abort_chunk_upload_quietly(
        self,
        upload_id: str,
        *,
        operator_params: dict[str, Any] | None,
        request_id: str | None,
    ) -> None:
        """尽力中止分块上传，忽略中止过程异常。"""
        try:
            await self.execute(
                InternalAPICall(
                    method="DELETE",
                    path=f"/internal/v1/files/upload/{upload_id}",
                    params=operator_params,
                    parser=_parse_chunk_upload_abort_result,
                ),
                request_id=request_id,
            )
        except (ServiceClientError, FileClientError) as exc:
            logger.warning(
                "中止分块上传失败 upload_id={} request_id={} error_type={}",
                upload_id,
                request_id,
                exc.__class__.__name__,
            )
            return

    async def _cleanup_uploaded_results(
        self,
        results: Sequence[FileUploadResult],
        *,
        request_id: str | None,
    ) -> None:
        """上传失败时回滚已上传成功的文件记录。"""
        file_ids = [item.record.id for item in results if item.record.id]
        if not file_ids:
            return
        deleted = await self.delete_files(file_ids, hard_delete=True, request_id=request_id)
        if deleted != len(file_ids):
            raise FileClientError(
                f"回滚删除数量不一致，期望 {len(file_ids)}，实际 {deleted}",
            )

    @staticmethod
    def _build_error_message(
        *,
        action: str,
        detail: str,
        rollback_failed: bool = False,
    ) -> str:
        if rollback_failed:
            return f"{action}失败且回滚失败：{detail}"
        return f"{action}失败：{detail}"

    @staticmethod
    def _build_chunk_part_call(
        *,
        upload_id: str,
        part_number: int,
        file: UploadFilePayload,
        chunk_payload: bytes,
        operator_params: dict[str, Any] | None,
    ) -> InternalAPICall[_ChunkPartUploadResult]:
        return InternalAPICall(
            method="PUT",
            path=f"/internal/v1/files/upload/{upload_id}/parts/{part_number}",
            params=operator_params,
            files=[
                (
                    "chunk",
                    (
                        file.filename,
                        chunk_payload,
                        file.content_type or "application/octet-stream",
                    ),
                )
            ],
            parser=_parse_chunk_part_upload_result,
        )

    @staticmethod
    def _validate_chunk_part_result(
        result: _ChunkPartUploadResult,
        *,
        upload_id: str,
        part_number: int,
    ) -> None:
        if result.upload_id != upload_id:
            raise FileClientError("分块上传响应 upload_id 不匹配")
        if result.part_number != part_number:
            raise FileClientError("分块上传响应 part_number 不匹配")
