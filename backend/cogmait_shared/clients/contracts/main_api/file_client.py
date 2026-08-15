"""内部文件服务 HTTP 客户端。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from ....core.coercion import parse_required_int, parse_strict_bool
from ....core.collections import deduplicate_preserving_order
from ....files import FileBusinessType, FileRecord, FileUploadResult, PresignedUrl
from ...core import (
    InternalAPICall,
    ServiceClientError,
)
from ._base import MainApiInternalClient
from ._upload import UploadFilePayload, _FileUploadMixin, _UploadExecutionOptions
from .errors import FileClientError
from .file_client_parsers import (
    _parse_deleted_count,
    _parse_file_manage_list,
    _parse_file_record,
    _parse_file_records,
    _parse_marked_count,
    _parse_presigned_batch,
)

__all__ = ["InternalFileClient", "FileClientError", "UploadFilePayload"]

# 小文件阈值：不超过该大小时优先请求更大的 part_size 以减少分片数量。
_DEFAULT_SMALL_FILE_THRESHOLD_BYTES = 10 * 1024 * 1024


def _normalize_positive_int(value: Any, *, field_name: str) -> int:
    try:
        parsed = parse_required_int(value, field_name=field_name)
    except ValueError as exc:
        raise FileClientError(str(exc)) from exc
    if parsed <= 0:
        raise FileClientError(f"{field_name} 必须为正整数")
    return parsed


def _normalize_optional_positive_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    return _normalize_positive_int(value, field_name=field_name)


def _normalize_bool_flag(value: Any, *, field_name: str) -> bool:
    parsed = parse_strict_bool(value)
    if parsed is None:
        raise FileClientError(f"{field_name} 必须是布尔值")
    return parsed


def _normalize_positive_int_sequence(values: Sequence[Any], *, field_name: str) -> list[int]:
    if isinstance(values, str | bytes):
        raise FileClientError(f"{field_name} 必须为列表")
    return deduplicate_preserving_order(
        _normalize_positive_int(value, field_name=field_name) for value in values
    )


def _normalize_file_type_sequence(values: Sequence[Any] | None) -> list[str]:
    if isinstance(values, str | bytes):
        raise FileClientError("file_types 必须为字符串列表")
    if not values:
        return []
    return deduplicate_preserving_order(_normalize_file_type(value) for value in values)


def _normalize_file_type(value: Any) -> str:
    if not isinstance(value, str):
        raise FileClientError("file_types 必须为字符串列表")
    parsed = value.strip().lower()
    if not parsed:
        raise FileClientError("file_types 不能为空")
    return parsed


def _normalize_optional_keyword(keyword: str | None) -> str:
    if keyword is None:
        return ""
    if not isinstance(keyword, str):
        raise FileClientError("keyword 必须为字符串")
    return keyword.strip()


class InternalFileClient(_FileUploadMixin, MainApiInternalClient):
    """封装调用 `main_api` `/internal/v1/files` 接口的逻辑。"""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_token: str | None = None,
        timeout: float = 10.0,
        small_file_threshold_bytes: int = _DEFAULT_SMALL_FILE_THRESHOLD_BYTES,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """初始化内部文件服务客户端。"""
        if isinstance(small_file_threshold_bytes, bool) or not isinstance(
            small_file_threshold_bytes, int
        ):
            raise ValueError("small_file_threshold_bytes 必须为正整数")
        if small_file_threshold_bytes <= 0:
            raise ValueError("small_file_threshold_bytes 必须为正整数")
        self._small_file_threshold_bytes = small_file_threshold_bytes
        super().__init__(
            base_url=base_url,
            api_token=api_token,
            timeout=timeout,
            client=client,
            transport=transport,
        )

    async def get(
        self,
        file_id: int,
        *,
        request_id: str | None = None,
    ) -> FileRecord:
        """查询单个文件记录。"""
        normalized_file_id = _normalize_positive_int(file_id, field_name="file_id")
        call = InternalAPICall(
            method="GET",
            path=f"/internal/v1/files/{normalized_file_id}",
            parser=_parse_file_record,
        )
        return await self._execute_file_call(
            call,
            request_id=request_id,
            action="请求文件服务",
        )

    async def upload(
        self,
        files: Sequence[UploadFilePayload],
        *,
        business_code: FileBusinessType | str = FileBusinessType.GENERAL,
        is_temporary: bool = False,
        ttl_seconds: int | None = None,
        operator_id: int | None = None,
        request_id: str | None = None,
    ) -> list[FileUploadResult]:
        """上传文件列表，内部走分块上传流程。"""
        if not files:
            return []
        normalized_is_temp = _normalize_bool_flag(is_temporary, field_name="is_temporary")
        normalized_ttl_seconds = _normalize_optional_positive_int(
            ttl_seconds,
            field_name="ttl_seconds",
        )
        normalized_operator_id = _normalize_optional_positive_int(
            operator_id,
            field_name="operator_id",
        )

        options = _UploadExecutionOptions(
            business_value=self._normalize_business_code(business_code),
            is_temporary=normalized_is_temp,
            ttl_seconds=normalized_ttl_seconds,
            operator_id=normalized_operator_id,
            operator_params=(
                {"operator_id": normalized_operator_id}
                if normalized_operator_id is not None
                else None
            ),
            request_id=request_id,
        )
        results: list[FileUploadResult] = []
        for file in files:
            await self._upload_single_file(
                file=file,
                options=options,
                uploaded_results=results,
            )
        return results

    @staticmethod
    def _normalize_business_code(business_code: FileBusinessType | str) -> str:
        if isinstance(business_code, FileBusinessType):
            return business_code.value
        if not isinstance(business_code, str):
            raise FileClientError("business_code 必须为字符串或 FileBusinessType")
        normalized = business_code.strip().upper()
        if not normalized:
            raise FileClientError("business_code 不能为空")
        try:
            return FileBusinessType(normalized).value
        except ValueError as exc:
            raise FileClientError("business_code 取值非法") from exc

    async def batch_query(
        self,
        file_ids: Sequence[int] | None = None,
        *,
        file_types: Sequence[str] | None = None,
        request_id: str | None = None,
    ) -> list[FileRecord]:
        """批量查询文件记录。"""
        normalized_file_ids = _normalize_positive_int_sequence(
            file_ids if file_ids is not None else [],
            field_name="file_ids",
        )
        normalized_file_types = _normalize_file_type_sequence(file_types)
        if not normalized_file_ids and not normalized_file_types:
            return []
        payload: dict[str, Any] = {}
        if normalized_file_ids:
            payload["file_ids"] = normalized_file_ids
        if normalized_file_types:
            payload["file_types"] = normalized_file_types
        call = InternalAPICall(
            method="POST",
            path="/internal/v1/files/query",
            json=payload,
            parser=_parse_file_records,
        )
        return await self._execute_file_call(
            call,
            request_id=request_id,
            action="批量查询文件",
        )

    async def search_files(
        self,
        *,
        file_ids: Sequence[int] | None = None,
        keyword: str | None = None,
        business_code: FileBusinessType | str | None = None,
        is_temporary: bool | None = None,
        page: int = 1,
        size: int = 20,
        request_id: str | None = None,
    ) -> tuple[list[FileRecord], int]:
        """分页查询文件记录。"""
        normalized_file_ids = _normalize_positive_int_sequence(
            file_ids if file_ids is not None else [],
            field_name="file_ids",
        )
        normalized_page = _normalize_positive_int(page, field_name="page")
        normalized_size = _normalize_positive_int(size, field_name="size")
        params: dict[str, Any] = {
            "page": str(normalized_page),
            "size": str(normalized_size),
        }
        if normalized_file_ids:
            params["file_ids"] = [str(item) for item in normalized_file_ids]
        normalized_keyword = _normalize_optional_keyword(keyword)
        if normalized_keyword:
            params["keyword"] = normalized_keyword
        if business_code is not None:
            params["business_code"] = self._normalize_business_code(business_code)
        if is_temporary is not None:
            params["is_temporary"] = (
                "true"
                if _normalize_bool_flag(
                    is_temporary,
                    field_name="is_temporary",
                )
                else "false"
            )
        call = InternalAPICall(
            method="GET",
            path="/internal/v1/files",
            params=params,
            parser=_parse_file_manage_list,
        )
        return await self._execute_file_call(
            call,
            request_id=request_id,
            action="分页查询文件",
        )

    async def presign_download(
        self,
        file_id: int,
        *,
        expires_in: int | None = None,
        request_id: str | None = None,
    ) -> PresignedUrl:
        """查询单文件预签名下载地址。"""
        normalized_file_id = _normalize_positive_int(file_id, field_name="file_id")
        batch = await self.batch_presign_download(
            [normalized_file_id],
            expires_in=expires_in,
            request_id=request_id,
        )
        if normalized_file_id not in batch:
            raise FileClientError("文件不存在或已删除")
        return batch[normalized_file_id]

    async def batch_presign_download(
        self,
        file_ids: Sequence[int],
        *,
        expires_in: int | None = None,
        request_id: str | None = None,
    ) -> dict[int, PresignedUrl]:
        """批量获取文件预签名下载地址。"""
        normalized_file_ids = _normalize_positive_int_sequence(file_ids, field_name="file_ids")
        normalized_expires_in = _normalize_optional_positive_int(
            expires_in,
            field_name="expires_in",
        )
        if not normalized_file_ids:
            return {}
        payload: dict[str, Any] = {
            "file_ids": normalized_file_ids,
        }
        if normalized_expires_in is not None:
            payload["expires_in"] = normalized_expires_in
        call = InternalAPICall(
            method="POST",
            path="/internal/v1/files/presign",
            json=payload,
            parser=_parse_presigned_batch,
        )
        return await self._execute_file_call(
            call,
            request_id=request_id,
            action="批量获取下载链接",
        )

    async def delete_files(
        self,
        file_ids: Sequence[int],
        *,
        hard_delete: bool = False,
        request_id: str | None = None,
    ) -> int:
        """批量删除文件。"""
        normalized_file_ids = _normalize_positive_int_sequence(file_ids, field_name="file_ids")
        if not normalized_file_ids:
            return 0
        normalized_hard_delete = _normalize_bool_flag(hard_delete, field_name="hard_delete")
        payload: dict[str, Any] = {
            "file_ids": normalized_file_ids,
        }
        if normalized_hard_delete:
            payload["hard_delete"] = True
        call = InternalAPICall(
            method="DELETE",
            path="/internal/v1/files",
            json=payload,
            parser=_parse_deleted_count,
        )
        return await self._execute_file_call(
            call,
            request_id=request_id,
            action="删除文件",
        )

    async def mark_files_temporary(
        self,
        file_ids: Sequence[int],
        *,
        request_id: str | None = None,
    ) -> int:
        """把文件标记为临时文件，交由文件清理任务处理。"""
        normalized_file_ids = _normalize_positive_int_sequence(file_ids, field_name="file_ids")
        if not normalized_file_ids:
            return 0
        call = InternalAPICall(
            method="PATCH",
            path="/internal/v1/files/mark-temporary",
            json={"file_ids": normalized_file_ids},
            parser=_parse_marked_count,
        )
        return await self._execute_file_call(
            call,
            request_id=request_id,
            action="标记临时文件",
        )

    async def _execute_file_call(
        self,
        call: InternalAPICall[Any],
        *,
        request_id: str | None,
        action: str,
    ) -> Any:
        try:
            return await self.execute(call, request_id=request_id)
        except ServiceClientError as exc:
            raise FileClientError(
                self._build_error_message(action=action, detail=exc.message),
                status_code=exc.status_code,
            ) from exc
