"""基于 MinIO SDK 封装的对象存储客户端。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Mapping
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from minio import Minio
from minio.deleteobjects import DeleteObject
from minio.error import S3Error

from ..observability.logging import logger

MetadataValue = str | list[str] | tuple[str, ...]
DEFAULT_PRESIGN_REGION = "us-east-1"
_UNSAFE_PREFIX_SEGMENTS = {"", ".", ".."}


class ObjectStorageClient(Minio):
    """提供对象存储桶操作辅助与更安全默认值。"""

    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool | None = None,
        region: str | None = None,
        presign_endpoint: str | None = None,
    ) -> None:
        host, inferred_secure = self._normalize_endpoint(endpoint)
        super().__init__(
            endpoint=host,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure if secure is not None else inferred_secure,
            region=region,
        )
        if presign_endpoint:
            presign_host, presign_secure = self._normalize_endpoint(presign_endpoint)
            self._presign_client: Minio = Minio(
                endpoint=presign_host,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure if secure is not None else presign_secure,
                region=region or DEFAULT_PRESIGN_REGION,
            )
        else:
            self._presign_client = self
        if not isinstance(bucket, str):
            raise ValueError("对象存储桶名称必须为字符串")
        normalized_bucket = bucket.strip()
        if not normalized_bucket:
            raise ValueError("对象存储桶名称不能为空")
        self._default_bucket = normalized_bucket
        self._event_loop_warning_emitted = False

    @staticmethod
    def _normalize_endpoint(raw_endpoint: str) -> tuple[str, bool]:
        """将带协议头的端点转换为 SDK 可识别的配置。"""
        if not isinstance(raw_endpoint, str):
            raise ValueError("对象存储端点地址必须为字符串")
        normalized = raw_endpoint.strip()
        if not normalized:
            raise ValueError("对象存储端点地址不能为空")
        if "://" in normalized:
            parsed = urlparse(normalized)
            if parsed.scheme not in {"http", "https"}:
                raise ValueError("对象存储端点地址协议仅支持 http/https")
            host = parsed.netloc or parsed.path
            if not host:
                raise ValueError("对象存储端点地址无效")
            return host, parsed.scheme == "https"
        return normalized, False

    @property
    def default_bucket(self) -> str:
        """返回为客户端配置的默认存储桶。"""
        return self._default_bucket

    @staticmethod
    def _normalize_object_name(object_name: str) -> str:
        if not isinstance(object_name, str):
            raise ValueError("object_name 必须为字符串")
        normalized = object_name.strip()
        if not normalized:
            raise ValueError("object_name 不能为空")
        return normalized

    @staticmethod
    def _normalize_delete_prefix(prefix: str) -> str:
        if not isinstance(prefix, str):
            raise ValueError("prefix 必须为字符串")
        normalized = prefix.strip()
        if not normalized:
            return ""
        if "\\" in normalized:
            raise ValueError("prefix 必须使用 / 分隔")
        if not normalized.endswith("/"):
            raise ValueError("prefix 必须以 / 结尾")
        trimmed = normalized[:-1]
        segments = trimmed.split("/")
        if len(segments) < 2:
            raise ValueError("prefix 至少需要包含一级目录和子目录")
        if any(segment in _UNSAFE_PREFIX_SEGMENTS for segment in segments):
            raise ValueError("prefix 不能包含空目录、. 或 ..")
        return f"{trimmed}/"

    def ensure_bucket(self, bucket_name: str | None = None, *, exist_ok: bool = True) -> str:
        """如果存储桶不存在则创建。"""
        self._warn_if_running_event_loop("ensure_bucket")
        target_bucket = self._resolve_bucket(bucket_name)
        try:
            if self.bucket_exists(bucket_name=target_bucket):
                if not exist_ok:
                    msg = f"桶 '{target_bucket}' 已存在"
                    raise ValueError(msg)
                return target_bucket
            self.make_bucket(bucket_name=target_bucket)
            return target_bucket
        except S3Error as exc:
            if exc.code in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"} and exist_ok:
                return target_bucket
            raise

    async def ensure_bucket_async(
        self,
        bucket_name: str | None = None,
        *,
        exist_ok: bool = True,
    ) -> str:
        """在线程池中执行桶初始化，避免阻塞事件循环。"""
        return await asyncio.to_thread(self.ensure_bucket, bucket_name, exist_ok=exist_ok)

    def ensure_public_bucket(self, bucket_name: str | None = None) -> None:
        """设置公共资源桶为公开读权限，不用于私有业务文件桶。"""
        self._warn_if_running_event_loop("ensure_public_bucket")
        target_bucket = self.ensure_bucket(bucket_name)
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{target_bucket}/*"],
                }
            ],
        }
        self.set_bucket_policy(bucket_name=target_bucket, policy=json.dumps(policy))

    async def ensure_public_bucket_async(self, bucket_name: str | None = None) -> None:
        """在线程池中执行公开桶初始化，避免阻塞事件循环。"""
        await asyncio.to_thread(self.ensure_public_bucket, bucket_name)

    async def bucket_exists_async(self, bucket_name: str | None = None) -> bool:
        """在线程池中检测桶是否存在。"""
        target_bucket = self._resolve_bucket(bucket_name)
        return await asyncio.to_thread(self.bucket_exists, target_bucket)

    def object_exists(self, object_name: str, *, bucket_name: str | None = None) -> bool:
        """检测对象是否存在，不会因未找到而抛错。"""
        self._warn_if_running_event_loop("object_exists")
        target_bucket = self._resolve_bucket(bucket_name)
        normalized_object_name = self._normalize_object_name(object_name)
        try:
            self.stat_object(
                bucket_name=target_bucket,
                object_name=normalized_object_name,
            )
            return True
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                return False
            raise

    def upload_bytes(
        self,
        object_name: str,
        data: bytes,
        *,
        bucket_name: str | None = None,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        """将字节数据上传到存储桶。"""
        self._warn_if_running_event_loop("upload_bytes")
        target_bucket = self._resolve_bucket(bucket_name)
        normalized_object_name = self._normalize_object_name(object_name)
        buffer = BytesIO(data)
        extra_kwargs = self._build_put_object_kwargs(
            content_type=content_type,
            metadata=metadata,
        )
        self.put_object(
            bucket_name=target_bucket,
            object_name=normalized_object_name,
            data=buffer,
            length=len(data),
            **extra_kwargs,
        )

    def upload_file(
        self,
        object_name: str,
        file_path: Path | str,
        *,
        bucket_name: str | None = None,
        content_type: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> None:
        """将磁盘文件上传到存储桶。"""
        self._warn_if_running_event_loop("upload_file")
        target_bucket = self._resolve_bucket(bucket_name)
        normalized_object_name = self._normalize_object_name(object_name)
        path = Path(file_path)
        with path.open("rb") as stream:
            extra_kwargs = self._build_put_object_kwargs(
                content_type=content_type,
                metadata=metadata,
            )
            self.put_object(
                bucket_name=target_bucket,
                object_name=normalized_object_name,
                data=stream,
                length=path.stat().st_size,
                **extra_kwargs,
            )

    @staticmethod
    def _build_put_object_kwargs(
        *,
        content_type: str | None,
        metadata: Mapping[str, str] | None,
    ) -> dict[str, Any]:
        extra_kwargs: dict[str, Any] = {}
        if content_type is not None:
            extra_kwargs["content_type"] = content_type
        if metadata is not None:
            extra_kwargs["metadata"] = cast(dict[str, MetadataValue], dict(metadata))
        return extra_kwargs

    def download_bytes(self, object_name: str, *, bucket_name: str | None = None) -> bytes:
        """下载对象并返回原始字节内容。"""
        self._warn_if_running_event_loop("download_bytes")
        target_bucket = self._resolve_bucket(bucket_name)
        normalized_object_name = self._normalize_object_name(object_name)
        response = self.get_object(
            bucket_name=target_bucket,
            object_name=normalized_object_name,
        )
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def remove_object_safe(self, object_name: str, *, bucket_name: str | None = None) -> None:
        """删除对象，若对象缺失则忽略。"""
        self._warn_if_running_event_loop("remove_object_safe")
        target_bucket = self._resolve_bucket(bucket_name)
        normalized_object_name = self._normalize_object_name(object_name)
        try:
            self.remove_object(
                bucket_name=target_bucket,
                object_name=normalized_object_name,
            )
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject"}:
                return
            raise

    def remove_objects_safe(
        self,
        object_names: Iterable[str],
        *,
        bucket_name: str | None = None,
        raise_on_error: bool = False,
    ) -> None:
        """批量删除多个对象。"""
        self._warn_if_running_event_loop("remove_objects_safe")
        target_bucket = self._resolve_bucket(bucket_name)
        if isinstance(object_names, str | bytes):
            raise ValueError("object_names 必须为字符串列表")
        delete_objects = [
            DeleteObject(self._normalize_object_name(object_name)) for object_name in object_names
        ]
        errors = list(
            self.remove_objects(
                bucket_name=target_bucket,
                delete_object_list=delete_objects,
            )
        )
        if errors and raise_on_error:
            raise RuntimeError(f"删除对象失败：失败数量 {len(errors)}")

    def list_object_names(
        self,
        *,
        bucket_name: str | None = None,
        prefix: str | None = None,
        recursive: bool = True,
    ) -> list[str]:
        """列举对象名称列表。"""
        self._warn_if_running_event_loop("list_object_names")
        target_bucket = self._resolve_bucket(bucket_name)
        iterator = self.list_objects(
            bucket_name=target_bucket,
            prefix=prefix,
            recursive=recursive,
        )
        return [item.object_name for item in iterator if item.object_name]

    def remove_prefix_safe(
        self,
        *,
        prefix: str,
        bucket_name: str | None = None,
    ) -> int:
        """按前缀批量删除对象，忽略对象不存在错误。"""
        self._warn_if_running_event_loop("remove_prefix_safe")
        normalized_prefix = self._normalize_delete_prefix(prefix)
        if not normalized_prefix:
            return 0
        target_bucket = self._resolve_bucket(bucket_name)
        object_names = self.list_object_names(
            bucket_name=target_bucket,
            prefix=normalized_prefix,
            recursive=True,
        )
        if not object_names:
            return 0
        self.remove_objects_safe(
            object_names,
            bucket_name=target_bucket,
            raise_on_error=True,
        )
        return len(object_names)

    def presigned_get_url(
        self,
        object_name: str,
        *,
        bucket_name: str | None = None,
        expires: timedelta | None = None,
    ) -> str:
        """生成预签名的 GET 链接。"""
        self._warn_if_running_event_loop("presigned_get_url")
        target_bucket = self._resolve_bucket(bucket_name)
        normalized_object_name = self._normalize_object_name(object_name)
        expiry = expires if expires is not None else timedelta(hours=1)
        return self._presign_client.presigned_get_object(
            bucket_name=target_bucket,
            object_name=normalized_object_name,
            expires=expiry,
        )

    async def presigned_get_url_async(
        self,
        object_name: str,
        *,
        bucket_name: str | None = None,
        expires: timedelta | None = None,
    ) -> str:
        """在线程池中生成预签名 GET 链接。"""
        return await asyncio.to_thread(
            self.presigned_get_url,
            object_name,
            bucket_name=bucket_name,
            expires=expires,
        )

    def presigned_put_url(
        self,
        object_name: str,
        *,
        bucket_name: str | None = None,
        expires: timedelta | None = None,
    ) -> str:
        """生成预签名的 PUT 链接。"""
        self._warn_if_running_event_loop("presigned_put_url")
        target_bucket = self._resolve_bucket(bucket_name)
        normalized_object_name = self._normalize_object_name(object_name)
        expiry = expires if expires is not None else timedelta(hours=1)
        return self._presign_client.presigned_put_object(
            bucket_name=target_bucket,
            object_name=normalized_object_name,
            expires=expiry,
        )

    async def presigned_put_url_async(
        self,
        object_name: str,
        *,
        bucket_name: str | None = None,
        expires: timedelta | None = None,
    ) -> str:
        """在线程池中生成预签名 PUT 链接。"""
        return await asyncio.to_thread(
            self.presigned_put_url,
            object_name,
            bucket_name=bucket_name,
            expires=expires,
        )

    def _resolve_bucket(self, bucket_name: str | None) -> str:
        candidate = bucket_name if bucket_name is not None else self._default_bucket
        if not isinstance(candidate, str):
            raise ValueError("bucket_name 必须为字符串")
        normalized = candidate.strip()
        if not normalized:
            raise ValueError("bucket_name 不能为空")
        return normalized

    def _warn_if_running_event_loop(self, method_name: str) -> None:
        if self._event_loop_warning_emitted:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        logger.warning(
            "检测到在事件循环中同步调用对象存储方法 {}，可能阻塞当前 worker，建议改为线程池包装。",
            method_name,
        )
        self._event_loop_warning_emitted = True
