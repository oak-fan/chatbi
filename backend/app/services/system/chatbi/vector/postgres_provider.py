"""ChatBI 向量 PostgreSQL 后端：委托仓储完成 pgvector 读写。"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from .....domain.system.chatbi.vector import (
    ChatbiBusinessKnowledgeSearchHit,
    ChatbiQsqlSearchHit,
    ChatbiSchemaSearchHit,
    ChatbiSchemaVectorRow,
)
from .....repositories.system.chatbi import (
    ChatbiBusinessKnowledgeVectorRepository,
    ChatbiQsqlVectorRepository,
    ChatbiSchemaVectorRepository,
)
from ...vector_store import VectorStoreSettings


class ChatbiVectorProvider(Protocol):
    async def rebuild_schema_vectors(
        self,
        *,
        datasource_id: int,
        rows: list[ChatbiSchemaVectorRow],
        user_id: int | None,
    ) -> None: ...

    async def search_schema(
        self,
        *,
        datasource_id: int,
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiSchemaSearchHit]: ...

    async def upsert_qsql_vector(
        self,
        *,
        qsql_id: int,
        datasource_id: int,
        embedding: list[float],
        user_id: int | None,
    ) -> None: ...

    async def soft_delete_qsql_vector(self, *, qsql_id: int, user_id: int | None) -> None: ...

    async def soft_delete_qsql_vectors_by_datasource(
        self,
        *,
        datasource_id: int,
        user_id: int | None,
    ) -> None: ...

    async def soft_delete_business_knowledge_vectors_by_ids(
        self,
        *,
        record_ids: list[int],
        user_id: int | None,
    ) -> None: ...

    async def search_qsql(
        self,
        *,
        datasource_id: int,
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiQsqlSearchHit]: ...

    async def search_qsql_pool(
        self,
        *,
        datasource_ids: list[int],
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiQsqlSearchHit]: ...

    async def upsert_business_knowledge_vector(
        self,
        *,
        business_knowledge_id: int,
        datasource_id: int,
        embedding: list[float],
        user_id: int | None,
    ) -> None: ...

    async def soft_delete_business_knowledge_vector(
        self,
        *,
        business_knowledge_id: int,
        user_id: int | None,
    ) -> None: ...

    async def search_business_knowledge(
        self,
        *,
        datasource_id: int,
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiBusinessKnowledgeSearchHit]: ...


class ChatbiPostgresVectorProvider:
    """PostgreSQL pgvector 向量后端，经仓储访问数据层。"""

    def __init__(self, *, session: AsyncSession, store_settings: VectorStoreSettings) -> None:
        self._schema_repo = ChatbiSchemaVectorRepository(session)
        self._qsql_repo = ChatbiQsqlVectorRepository(session)
        self._bizkn_repo = ChatbiBusinessKnowledgeVectorRepository(session)

    async def rebuild_schema_vectors(
        self,
        *,
        datasource_id: int,
        rows: list[ChatbiSchemaVectorRow],
        user_id: int | None,
    ) -> None:
        await self._schema_repo.rebuild_vectors(
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
        return await self._schema_repo.search_nearest_by_datasource(
            datasource_id,
            embedding,
            top_k,
        )

    async def upsert_qsql_vector(
        self,
        *,
        qsql_id: int,
        datasource_id: int,
        embedding: list[float],
        user_id: int | None,
    ) -> None:
        await self._qsql_repo.upsert_vector(
            qsql_id=qsql_id,
            datasource_id=datasource_id,
            embedding=embedding,
            user_id=user_id,
        )

    async def soft_delete_qsql_vector(self, *, qsql_id: int, user_id: int | None) -> None:
        await self._qsql_repo.soft_delete_by_qsql_id(qsql_id=qsql_id, user_id=user_id)

    async def soft_delete_qsql_vectors_by_datasource(
        self,
        *,
        datasource_id: int,
        user_id: int | None,
    ) -> None:
        await self._qsql_repo.soft_delete_by_datasource(
            datasource_id=datasource_id,
            user_id=user_id,
        )

    async def soft_delete_business_knowledge_vectors_by_ids(
        self,
        *,
        record_ids: list[int],
        user_id: int | None,
    ) -> None:
        await self._bizkn_repo.soft_delete_by_business_knowledge_ids(
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
        return await self._qsql_repo.search_nearest_by_datasource(
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
        return await self._qsql_repo.search_nearest_by_datasources(
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
        await self._bizkn_repo.upsert_vector(
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
        await self._bizkn_repo.soft_delete_by_business_knowledge_id(
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
        return await self._bizkn_repo.search_nearest_by_datasource(
            datasource_id=datasource_id,
            embedding=embedding,
            top_k=top_k,
        )


__all__ = ["ChatbiPostgresVectorProvider", "ChatbiVectorProvider"]
