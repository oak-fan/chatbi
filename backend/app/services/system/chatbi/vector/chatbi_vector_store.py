"""ChatBI 统一向量门面。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .....constants.chatbi.datasource import CHATBI_VECTOR_DIMENSIONS
from .....core.config import Settings, settings
from .....domain.system.chatbi.vector import (
    ChatbiBusinessKnowledgeSearchHit,
    ChatbiQsqlSearchHit,
    ChatbiSchemaSearchHit,
    ChatbiSchemaVectorRow,
)
from .....domain.system.vector import VectorBackendType
from ...vector_store import (
    VectorStoreError,
    VectorStoreSettings,
    build_vector_store_settings,
    initialize_vector_backend,
)
from .milvus_provider import ChatbiMilvusVectorProvider
from .postgres_provider import ChatbiPostgresVectorProvider, ChatbiVectorProvider

ChatbiVectorSettings = VectorStoreSettings


def build_chatbi_vector_settings(config: Settings = settings) -> ChatbiVectorSettings:
    """复用全局 VECTOR_BACKEND / 维度 / Milvus 配置。"""
    base = build_vector_store_settings(config)
    return VectorStoreSettings(
        backend=base.backend,
        dimensions=CHATBI_VECTOR_DIMENSIONS,
        default_top_k=base.default_top_k,
        timeout_seconds=base.timeout_seconds,
        postgres_ivfflat_lists=base.postgres_ivfflat_lists,
        milvus_uri=base.milvus_uri,
        milvus_token=base.milvus_token,
        milvus_database=base.milvus_database,
        milvus_collection_prefix=base.milvus_collection_prefix,
    )


def initialize_chatbi_vector_backend(store_settings: ChatbiVectorSettings) -> None:
    """启动期初始化 Milvus collections（postgres 无额外步骤）。"""
    if store_settings.backend is VectorBackendType.MILVUS:
        ChatbiMilvusVectorProvider(store_settings=store_settings).initialize()
    else:
        initialize_vector_backend(store_settings)


class ChatbiVectorStore:
    """按 VECTOR_BACKEND 委托 postgres 或 milvus provider。"""

    def __init__(
        self,
        *,
        session: AsyncSession,
        store_settings: ChatbiVectorSettings | None = None,
        provider: ChatbiVectorProvider | None = None,
    ) -> None:
        self._settings = store_settings or build_chatbi_vector_settings()
        self._provider = provider or self._build_provider(session=session)

    @property
    def dimensions(self) -> int:
        return self._settings.dimensions

    def _validate_embedding(self, embedding: list[float]) -> None:
        if len(embedding) != self._settings.dimensions:
            raise VectorStoreError(
                f"向量维度不匹配，期望 {self._settings.dimensions}，实际 {len(embedding)}"
            )

    def _build_provider(self, *, session: AsyncSession) -> ChatbiVectorProvider:
        if self._settings.backend is VectorBackendType.POSTGRES:
            return ChatbiPostgresVectorProvider(session=session, store_settings=self._settings)
        return ChatbiMilvusVectorProvider(store_settings=self._settings)

    async def rebuild_schema_vectors(
        self,
        *,
        datasource_id: int,
        rows: list[ChatbiSchemaVectorRow],
        user_id: int | None,
    ) -> None:
        for row in rows:
            self._validate_embedding(row.embedding)
        await self._provider.rebuild_schema_vectors(
            datasource_id=datasource_id,
            rows=rows,
            user_id=user_id,
        )

    async def search_schema(
        self,
        *,
        datasource_id: int,
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiSchemaSearchHit]:
        self._validate_embedding(embedding)
        return await self._provider.search_schema(
            datasource_id=datasource_id,
            embedding=embedding,
            top_k=top_k,
        )

    async def upsert_qsql_vector(
        self,
        *,
        qsql_id: int,
        datasource_id: int,
        embedding: list[float],
        user_id: int | None,
    ) -> None:
        self._validate_embedding(embedding)
        await self._provider.upsert_qsql_vector(
            qsql_id=qsql_id,
            datasource_id=datasource_id,
            embedding=embedding,
            user_id=user_id,
        )

    async def soft_delete_qsql_vector(self, *, qsql_id: int, user_id: int | None) -> None:
        await self._provider.soft_delete_qsql_vector(qsql_id=qsql_id, user_id=user_id)

    async def soft_delete_qsql_vectors_by_datasource(
        self,
        *,
        datasource_id: int,
        user_id: int | None,
    ) -> None:
        await self._provider.soft_delete_qsql_vectors_by_datasource(
            datasource_id=datasource_id,
            user_id=user_id,
        )

    async def soft_delete_business_knowledge_vectors_by_ids(
        self,
        *,
        record_ids: list[int],
        user_id: int | None,
    ) -> None:
        await self._provider.soft_delete_business_knowledge_vectors_by_ids(
            record_ids=record_ids,
            user_id=user_id,
        )

    async def search_qsql(
        self,
        *,
        datasource_id: int,
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiQsqlSearchHit]:
        self._validate_embedding(embedding)
        return await self._provider.search_qsql(
            datasource_id=datasource_id,
            embedding=embedding,
            top_k=top_k,
        )

    async def search_qsql_pool(
        self,
        *,
        datasource_ids: list[int],
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiQsqlSearchHit]:
        self._validate_embedding(embedding)
        return await self._provider.search_qsql_pool(
            datasource_ids=datasource_ids,
            embedding=embedding,
            top_k=top_k,
        )

    async def upsert_business_knowledge_vector(
        self,
        *,
        business_knowledge_id: int,
        datasource_id: int,
        embedding: list[float],
        user_id: int | None,
    ) -> None:
        self._validate_embedding(embedding)
        await self._provider.upsert_business_knowledge_vector(
            business_knowledge_id=business_knowledge_id,
            datasource_id=datasource_id,
            embedding=embedding,
            user_id=user_id,
        )

    async def soft_delete_business_knowledge_vector(
        self,
        *,
        business_knowledge_id: int,
        user_id: int | None,
    ) -> None:
        await self._provider.soft_delete_business_knowledge_vector(
            business_knowledge_id=business_knowledge_id,
            user_id=user_id,
        )

    async def search_business_knowledge(
        self,
        *,
        datasource_id: int,
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiBusinessKnowledgeSearchHit]:
        self._validate_embedding(embedding)
        return await self._provider.search_business_knowledge(
            datasource_id=datasource_id,
            embedding=embedding,
            top_k=top_k,
        )


__all__ = [
    "ChatbiVectorSettings",
    "ChatbiVectorStore",
    "build_chatbi_vector_settings",
    "initialize_chatbi_vector_backend",
]
