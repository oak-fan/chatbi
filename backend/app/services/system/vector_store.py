"""统一向量能力与 provider 实现。"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any, Protocol, cast

from sqlalchemy import bindparam, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import Settings, settings
from ...domain.system.vector import (
    VectorBackendType,
    VectorChunkInput,
    VectorHealthRecord,
    VectorSearchHit,
    VectorSearchInput,
)

__all__ = [
    "VectorStore",
    "VectorStoreError",
    "VectorStoreSettings",
    "build_vector_store_settings",
    "initialize_vector_backend",
]


@dataclass(frozen=True, slots=True)
class VectorStoreSettings:
    """向量存储配置。"""

    backend: VectorBackendType
    dimensions: int
    default_top_k: int
    timeout_seconds: float
    postgres_ivfflat_lists: int
    milvus_uri: str | None
    milvus_token: str | None
    milvus_database: str
    milvus_collection_prefix: str


class VectorStoreError(Exception):
    """统一向量存储异常。"""


class VectorStoreProvider(Protocol):
    """向量 provider 协议。"""

    async def upsert_chunks(
        self,
        chunks: list[VectorChunkInput],
        *,
        user_id: int | None,
    ) -> None: ...

    async def delete_by_file(
        self,
        *,
        knowledge_id: int,
        file_id: int,
        user_id: int | None,
    ) -> None: ...

    async def delete_by_chunk_ids(
        self,
        chunk_ids: list[int],
        *,
        user_id: int | None,
    ) -> None: ...

    async def delete_by_knowledge(
        self,
        *,
        knowledge_id: int,
        user_id: int | None,
    ) -> None: ...

    async def search(self, payload: VectorSearchInput) -> list[VectorSearchHit]: ...

    async def health_check(self) -> VectorHealthRecord: ...

    async def rebuild(
        self,
        *,
        knowledge_id: int,
        chunks: list[VectorChunkInput],
        user_id: int | None,
    ) -> None: ...


def build_vector_store_settings(config: Settings = settings) -> VectorStoreSettings:
    """构建并校验向量存储配置。"""

    try:
        backend = VectorBackendType(config.vector_backend)
    except ValueError as exc:
        raise ValueError("VECTOR_BACKEND 仅支持 postgres 或 milvus") from exc
    if config.vector_dimensions <= 0:
        raise ValueError("VECTOR_DIMENSIONS 必须大于 0")
    if config.vector_default_top_k <= 0:
        raise ValueError("VECTOR_DEFAULT_TOP_K 必须大于 0")
    if config.vector_timeout <= 0:
        raise ValueError("VECTOR_TIMEOUT 必须大于 0")
    if config.vector_postgres_ivfflat_lists <= 0:
        raise ValueError("VECTOR_POSTGRES_IVFFLAT_LISTS 必须大于 0")
    if backend is VectorBackendType.MILVUS:
        if not config.milvus_uri:
            raise ValueError("启用 Milvus 后端时必须配置 MILVUS_URI")
        if not config.milvus_collection_prefix:
            raise ValueError("启用 Milvus 后端时必须配置 MILVUS_COLLECTION_PREFIX")
        if importlib.util.find_spec("pymilvus") is None:
            raise ValueError("当前环境缺少 pymilvus，无法启用 Milvus 后端")
    return VectorStoreSettings(
        backend=backend,
        dimensions=config.vector_dimensions,
        default_top_k=config.vector_default_top_k,
        timeout_seconds=config.vector_timeout,
        postgres_ivfflat_lists=config.vector_postgres_ivfflat_lists,
        milvus_uri=config.milvus_uri,
        milvus_token=config.milvus_token,
        milvus_database=config.milvus_database,
        milvus_collection_prefix=config.milvus_collection_prefix,
    )


def initialize_vector_backend(store_settings: VectorStoreSettings) -> None:
    """在启动阶段初始化当前后端的最小资源。"""

    if store_settings.backend is VectorBackendType.MILVUS:
        MilvusVectorStore(store_settings=store_settings).initialize()


class VectorStore:
    """统一向量能力入口。"""

    def __init__(
        self,
        *,
        session: AsyncSession,
        store_settings: VectorStoreSettings,
        provider: VectorStoreProvider | None = None,
    ) -> None:
        self._settings = store_settings
        self._provider = provider or self._build_provider(session=session)

    @property
    def backend(self) -> VectorBackendType:
        return self._settings.backend

    @property
    def dimensions(self) -> int:
        return self._settings.dimensions

    @property
    def default_top_k(self) -> int:
        return self._settings.default_top_k

    async def upsert_chunks(self, chunks: list[VectorChunkInput], *, user_id: int | None) -> None:
        self._validate_chunks(chunks)
        await self._provider.upsert_chunks(chunks, user_id=user_id)

    async def delete_by_file(
        self,
        *,
        knowledge_id: int,
        file_id: int,
        user_id: int | None,
    ) -> None:
        await self._provider.delete_by_file(
            knowledge_id=knowledge_id,
            file_id=file_id,
            user_id=user_id,
        )

    async def delete_by_chunk_ids(self, chunk_ids: list[int], *, user_id: int | None) -> None:
        await self._provider.delete_by_chunk_ids(chunk_ids, user_id=user_id)

    async def delete_by_knowledge(
        self,
        *,
        knowledge_id: int,
        user_id: int | None,
    ) -> None:
        await self._provider.delete_by_knowledge(
            knowledge_id=knowledge_id,
            user_id=user_id,
        )

    async def search(self, payload: VectorSearchInput) -> list[VectorSearchHit]:
        self._validate_embedding(payload.embedding)
        return await self._provider.search(payload)

    async def health_check(self) -> VectorHealthRecord:
        return await self._provider.health_check()

    async def rebuild(
        self,
        *,
        knowledge_id: int,
        chunks: list[VectorChunkInput],
        user_id: int | None,
    ) -> None:
        self._validate_chunks(chunks)
        await self._provider.rebuild(
            knowledge_id=knowledge_id,
            chunks=chunks,
            user_id=user_id,
        )

    def _validate_chunks(self, chunks: list[VectorChunkInput]) -> None:
        if not chunks:
            return
        for chunk in chunks:
            self._validate_embedding(chunk.embedding)

    def _validate_embedding(self, embedding: list[float]) -> None:
        if len(embedding) != self._settings.dimensions:
            raise VectorStoreError(
                f"向量维度不匹配，期望 {self._settings.dimensions}，实际 {len(embedding)}"
            )

    def _build_provider(self, *, session: AsyncSession) -> VectorStoreProvider:
        if self._settings.backend is VectorBackendType.POSTGRES:
            return PostgresVectorStore(session=session, store_settings=self._settings)
        return MilvusVectorStore(store_settings=self._settings)


class PostgresVectorStore:
    """PostgreSQL pgvector 实现。"""

    def __init__(self, *, session: AsyncSession, store_settings: VectorStoreSettings) -> None:
        self._session = session
        self._settings = store_settings

    async def upsert_chunks(self, chunks: list[VectorChunkInput], *, user_id: int | None) -> None:
        if not chunks:
            return
        await self._ensure_postgres()
        stmt = text(
            """
            INSERT INTO ais_knowledge_chunk_vector (
                chunk_id,
                knowledge_id,
                file_id,
                result_file_id,
                embedding,
                is_deleted,
                created_by,
                updated_by
            ) VALUES (
                :chunk_id,
                :knowledge_id,
                :file_id,
                :result_file_id,
                CAST(:embedding AS vector),
                FALSE,
                :user_id,
                :user_id
            )
            ON CONFLICT (chunk_id) DO UPDATE
            SET
                knowledge_id = EXCLUDED.knowledge_id,
                file_id = EXCLUDED.file_id,
                result_file_id = EXCLUDED.result_file_id,
                embedding = EXCLUDED.embedding,
                is_deleted = FALSE,
                updated_at = NOW(),
                updated_by = EXCLUDED.updated_by
            """
        )
        await self._session.execute(
            stmt,
            [
                {
                    "chunk_id": chunk.chunk_id,
                    "knowledge_id": chunk.knowledge_id,
                    "file_id": chunk.file_id,
                    "result_file_id": chunk.result_file_id,
                    "embedding": _to_pgvector_literal(chunk.embedding),
                    "user_id": user_id,
                }
                for chunk in chunks
            ],
        )

    async def delete_by_file(
        self,
        *,
        knowledge_id: int,
        file_id: int,
        user_id: int | None,
    ) -> None:
        await self._ensure_postgres()
        await self._session.execute(
            text(
                """
                UPDATE ais_knowledge_chunk_vector
                SET
                    is_deleted = TRUE,
                    updated_at = NOW(),
                    updated_by = :user_id
                WHERE knowledge_id = :knowledge_id
                  AND file_id = :file_id
                  AND is_deleted = FALSE
                """
            ),
            {
                "knowledge_id": knowledge_id,
                "file_id": file_id,
                "user_id": user_id,
            },
        )

    async def delete_by_knowledge(
        self,
        *,
        knowledge_id: int,
        user_id: int | None,
    ) -> None:
        await self._ensure_postgres()
        await self._session.execute(
            text(
                """
                UPDATE ais_knowledge_chunk_vector
                SET
                    is_deleted = TRUE,
                    updated_at = NOW(),
                    updated_by = :user_id
                WHERE knowledge_id = :knowledge_id
                  AND is_deleted = FALSE
                """
            ),
            {
                "knowledge_id": knowledge_id,
                "user_id": user_id,
            },
        )

    async def delete_by_chunk_ids(self, chunk_ids: list[int], *, user_id: int | None) -> None:
        if not chunk_ids:
            return
        await self._ensure_postgres()
        stmt = text(
            """
            UPDATE ais_knowledge_chunk_vector
            SET
                is_deleted = TRUE,
                updated_at = NOW(),
                updated_by = :user_id
            WHERE chunk_id IN :chunk_ids
              AND is_deleted = FALSE
            """
        ).bindparams(bindparam("chunk_ids", expanding=True))
        await self._session.execute(
            stmt,
            {
                "chunk_ids": chunk_ids,
                "user_id": user_id,
            },
        )

    async def search(self, payload: VectorSearchInput) -> list[VectorSearchHit]:
        await self._ensure_postgres()
        sql = """
            SELECT
                chunk_id,
                file_id,
                1 - (embedding <=> CAST(:embedding AS vector)) AS score
            FROM ais_knowledge_chunk_vector
            WHERE knowledge_id = :knowledge_id
              AND is_deleted = FALSE
        """
        params: dict[str, Any] = {
            "knowledge_id": payload.knowledge_id,
            "embedding": _to_pgvector_literal(payload.embedding),
            "top_k": payload.top_k,
        }
        if payload.file_ids:
            sql += "\n  AND file_id IN :file_ids"
        if payload.result_file_ids:
            sql += "\n  AND result_file_id IN :result_file_ids"
        if payload.score_threshold is not None:
            sql += "\n  AND 1 - (embedding <=> CAST(:embedding AS vector)) >= :score_threshold"
            params["score_threshold"] = payload.score_threshold
        sql += "\nORDER BY embedding <=> CAST(:embedding AS vector), chunk_id LIMIT :top_k"
        stmt = text(sql)
        if payload.file_ids:
            stmt = stmt.bindparams(bindparam("file_ids", expanding=True))
            params["file_ids"] = payload.file_ids
        if payload.result_file_ids:
            stmt = stmt.bindparams(bindparam("result_file_ids", expanding=True))
            params["result_file_ids"] = payload.result_file_ids
        result = await self._session.execute(stmt, params)
        return [_row_to_hit(row) for row in result.mappings().all()]

    async def health_check(self) -> VectorHealthRecord:
        await self._ensure_postgres()
        detail: dict[str, Any] = {"extension": False, "table_ready": False}
        extension_result = await self._session.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        )
        extension_name = extension_result.scalar_one_or_none()
        detail["extension"] = extension_name == "vector"
        table_result = await self._session.execute(
            text(
                """
                SELECT format_type(a.atttypid, a.atttypmod)
                FROM pg_attribute AS a
                JOIN pg_class AS c ON c.oid = a.attrelid
                WHERE c.relname = 'ais_knowledge_chunk_vector'
                  AND a.attname = 'embedding'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                """
            )
        )
        embedding_type = table_result.scalar_one_or_none()
        detail["embedding_type"] = embedding_type
        detail["table_ready"] = isinstance(embedding_type, str) and embedding_type.startswith(
            "vector("
        )
        detail["expected_dimensions"] = self._settings.dimensions
        detail["dimension_matched"] = embedding_type == f"vector({self._settings.dimensions})"
        is_healthy = bool(
            detail["extension"] and detail["table_ready"] and detail["dimension_matched"]
        )
        return VectorHealthRecord(
            backend=VectorBackendType.POSTGRES,
            is_healthy=is_healthy,
            detail=detail,
        )

    async def rebuild(
        self,
        *,
        knowledge_id: int,
        chunks: list[VectorChunkInput],
        user_id: int | None,
    ) -> None:
        await self.delete_by_knowledge(knowledge_id=knowledge_id, user_id=user_id)
        await self.upsert_chunks(chunks, user_id=user_id)

    async def _ensure_postgres(self) -> None:
        dialect_name = self._session.bind.dialect.name if self._session.bind is not None else ""
        if dialect_name != "postgresql":
            raise VectorStoreError("PostgreSQL 向量后端只能运行在 PostgreSQL 数据库上")


class MilvusVectorStore:
    """Milvus 实现。"""

    _COLLECTION_NAME = "knowledge_chunk"

    def __init__(self, *, store_settings: VectorStoreSettings) -> None:
        self._settings = store_settings

    def initialize(self) -> None:
        client = self._get_client()
        collection_name = self._collection_name()
        client.create_collection_if_missing(collection_name=collection_name)
        self._validate_collection_dimension(client=client, collection_name=collection_name)

    async def upsert_chunks(self, chunks: list[VectorChunkInput], *, user_id: int | None) -> None:
        if not chunks:
            return
        client = self._get_client()
        collection_name = self._collection_name()
        self._require_collection(client, collection_name)
        client.delete(
            collection_name=collection_name,
            ids=[chunk.chunk_id for chunk in chunks],
            timeout=self._settings.timeout_seconds,
        )
        client.insert(
            collection_name=collection_name,
            data=[
                {
                    "chunk_id": chunk.chunk_id,
                    "knowledge_id": chunk.knowledge_id,
                    "file_id": chunk.file_id,
                    "result_file_id": chunk.result_file_id,
                    "embedding": chunk.embedding,
                }
                for chunk in chunks
            ],
            timeout=self._settings.timeout_seconds,
        )

    async def delete_by_file(
        self,
        *,
        knowledge_id: int,
        file_id: int,
        user_id: int | None,
    ) -> None:
        del user_id
        client = self._get_client()
        collection_name = self._collection_name()
        self._require_collection(client, collection_name)
        client.delete(
            collection_name=collection_name,
            filter=(f"knowledge_id == {knowledge_id} and file_id == {file_id}"),
            timeout=self._settings.timeout_seconds,
        )

    async def delete_by_knowledge(
        self,
        *,
        knowledge_id: int,
        user_id: int | None,
    ) -> None:
        del user_id
        client = self._get_client()
        collection_name = self._collection_name()
        self._require_collection(client, collection_name)
        client.delete(
            collection_name=collection_name,
            filter=f"knowledge_id == {knowledge_id}",
            timeout=self._settings.timeout_seconds,
        )

    async def delete_by_chunk_ids(self, chunk_ids: list[int], *, user_id: int | None) -> None:
        del user_id
        if not chunk_ids:
            return
        client = self._get_client()
        collection_name = self._collection_name()
        self._require_collection(client, collection_name)
        client.delete(
            collection_name=collection_name,
            ids=chunk_ids,
            timeout=self._settings.timeout_seconds,
        )

    async def search(self, payload: VectorSearchInput) -> list[VectorSearchHit]:
        client = self._get_client()
        collection_name = self._collection_name()
        self._require_collection(client, collection_name)
        search_result = client.search(
            collection_name=collection_name,
            data=[payload.embedding],
            filter=_build_milvus_filter(
                knowledge_id=payload.knowledge_id,
                file_ids=payload.file_ids,
                result_file_ids=payload.result_file_ids,
            ),
            limit=payload.top_k,
            output_fields=["file_id"],
            search_params={"metric_type": "COSINE", "params": {}},
            timeout=self._settings.timeout_seconds,
        )
        rows = (
            search_result[0]
            if search_result and isinstance(search_result[0], list)
            else search_result
        )
        hits: list[VectorSearchHit] = []
        for row in rows:
            score = float(row.get("distance") or 0.0)
            if payload.score_threshold is not None and score < payload.score_threshold:
                continue
            entity = row.get("entity") or {}
            hits.append(
                VectorSearchHit(
                    chunk_id=int(row["id"]),
                    file_id=int(entity["file_id"]),
                    score=score,
                )
            )
        return hits

    async def health_check(self) -> VectorHealthRecord:
        client = self._get_client()
        collection_name = self._collection_name()
        collection_exists = bool(
            client.has_collection(
                collection_name=collection_name,
                timeout=self._settings.timeout_seconds,
            )
        )
        detail: dict[str, Any] = {
            "collection_name": collection_name,
            "collection_exists": collection_exists,
            "database": self._settings.milvus_database,
            "expected_dimensions": self._settings.dimensions,
        }
        if collection_exists:
            actual_dimensions = client.get_collection_dimension(collection_name=collection_name)
            detail["actual_dimensions"] = actual_dimensions
            detail["dimension_matched"] = actual_dimensions == self._settings.dimensions
            detail["load_state"] = client.get_load_state(
                collection_name=collection_name,
                timeout=self._settings.timeout_seconds,
            )
        else:
            detail["actual_dimensions"] = None
            detail["dimension_matched"] = False
        return VectorHealthRecord(
            backend=VectorBackendType.MILVUS,
            is_healthy=collection_exists and bool(detail["dimension_matched"]),
            detail=detail,
        )

    async def rebuild(
        self,
        *,
        knowledge_id: int,
        chunks: list[VectorChunkInput],
        user_id: int | None,
    ) -> None:
        await self.delete_by_knowledge(knowledge_id=knowledge_id, user_id=user_id)
        await self.upsert_chunks(chunks, user_id=user_id)

    def _get_client(self) -> Any:
        try:
            from pymilvus import DataType, MilvusClient
        except ImportError as exc:  # pragma: no cover - 依赖缺失由配置校验兜住
            raise VectorStoreError("当前环境缺少 pymilvus，无法使用 Milvus 后端") from exc
        if self._settings.milvus_uri is None or self._settings.milvus_token is None:
            raise VectorStoreError("Milvus 连接配置不完整")
        return _MilvusClientAdapter(
            client=MilvusClient(
                uri=cast(str, self._settings.milvus_uri),
                token=self._settings.milvus_token or "",
                db_name=self._settings.milvus_database,
                timeout=self._settings.timeout_seconds,
            ),
            data_type=DataType,
            dimensions=self._settings.dimensions,
        )

    def _collection_name(self) -> str:
        return f"{self._settings.milvus_collection_prefix}_{self._COLLECTION_NAME}"

    def _validate_collection_dimension(self, *, client: Any, collection_name: str) -> None:
        actual_dimensions = client.get_collection_dimension(collection_name=collection_name)
        if actual_dimensions != self._settings.dimensions:
            raise VectorStoreError(
                "Milvus collection 向量维度不匹配，"
                f"期望 {self._settings.dimensions}，实际 {actual_dimensions}"
            )

    def _require_collection(self, client: Any, collection_name: str) -> None:
        if client.has_collection(collection_name=collection_name):
            self._validate_collection_dimension(client=client, collection_name=collection_name)
            return
        raise VectorStoreError(f"Milvus collection {collection_name} 未初始化，请先完成启动初始化")


class _MilvusClientAdapter:
    """适配 MilvusClient，集中处理初始化差异。"""

    def __init__(self, *, client: Any, data_type: Any, dimensions: int) -> None:
        self._client = client
        self._data_type = data_type
        self._dimensions = dimensions

    def create_collection_if_missing(self, *, collection_name: str) -> None:
        if self._client.has_collection(collection_name=collection_name):
            return
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(
            field_name="chunk_id",
            datatype=self._data_type.INT64,
            is_primary=True,
        )
        schema.add_field(field_name="knowledge_id", datatype=self._data_type.INT64)
        schema.add_field(field_name="file_id", datatype=self._data_type.INT64)
        schema.add_field(field_name="result_file_id", datatype=self._data_type.INT64)
        schema.add_field(
            field_name="embedding",
            datatype=self._data_type.FLOAT_VECTOR,
            dim=self._dimensions,
        )
        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="AUTOINDEX",
            metric_type="COSINE",
            params={},
        )
        self._client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params,
        )

    def get_collection_dimension(self, *, collection_name: str) -> int | None:
        if not hasattr(self._client, "describe_collection"):
            return None
        description = self._client.describe_collection(collection_name=collection_name)
        if not isinstance(description, dict):
            return None
        fields = description.get("fields")
        if not isinstance(fields, list):
            return None
        for field in fields:
            if not isinstance(field, dict):
                continue
            field_name = field.get("name") or field.get("field_name")
            if field_name != "embedding":
                continue
            for key in ("dim",):
                value = field.get(key)
                if value is not None:
                    return int(value)
            for key in ("params", "type_params"):
                params = field.get(key)
                if isinstance(params, dict) and params.get("dim") is not None:
                    return int(params["dim"])
        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def _to_pgvector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.12g}" for value in embedding) + "]"


def _row_to_hit(row: RowMapping) -> VectorSearchHit:
    return VectorSearchHit(
        chunk_id=int(row["chunk_id"]),
        file_id=int(row["file_id"]),
        score=float(row["score"]),
    )


def _build_milvus_filter(
    *,
    knowledge_id: int,
    file_ids: list[int] | None,
    result_file_ids: list[int] | None,
) -> str:
    expressions = [f"knowledge_id == {knowledge_id}"]
    if file_ids:
        file_literal = ", ".join(str(file_id) for file_id in file_ids)
        expressions.append(f"file_id in [{file_literal}]")
    if result_file_ids:
        result_file_literal = ", ".join(str(file_id) for file_id in result_file_ids)
        expressions.append(f"result_file_id in [{result_file_literal}]")
    return " and ".join(expressions)
