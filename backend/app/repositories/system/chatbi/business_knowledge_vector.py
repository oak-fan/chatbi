"""ChatBI 业务知识向量数据访问。"""

from __future__ import annotations

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from cogmait_shared.core.id_generator import generate_snowflake_id

from ....domain.system.chatbi import ChatbiBusinessKnowledgeScope
from ....domain.system.chatbi.vector import ChatbiBusinessKnowledgeSearchHit
from ....models.system.chatbi import ChatbiBusinessKnowledgeVector
from .pgvector import to_pgvector_literal


class ChatbiBusinessKnowledgeVectorRepository:
    """封装 ais_chatbi_business_knowledge_vector 表的读写。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_vector(
        self,
        *,
        business_knowledge_id: int,
        datasource_id: int,
        embedding: list[float],
        user_id: int | None,
    ) -> None:
        await self.soft_delete_by_business_knowledge_id(
            business_knowledge_id=business_knowledge_id,
            user_id=user_id,
        )
        stmt = text(
            """
            INSERT INTO ais_chatbi_business_knowledge_vector (
                id, business_knowledge_id, datasource_id, embedding,
                created_by, updated_by, is_deleted
            ) VALUES (
                :id, :business_knowledge_id, :datasource_id, CAST(:embedding AS vector),
                :user_id, :user_id, FALSE
            )
            """
        )
        await self._session.execute(
            stmt,
            {
                "id": generate_snowflake_id(),
                "business_knowledge_id": business_knowledge_id,
                "datasource_id": datasource_id,
                "embedding": to_pgvector_literal(embedding),
                "user_id": user_id,
            },
        )

    async def soft_delete_by_business_knowledge_id(
        self,
        *,
        business_knowledge_id: int,
        user_id: int | None,
    ) -> None:
        stmt = (
            update(ChatbiBusinessKnowledgeVector)
            .where(
                ChatbiBusinessKnowledgeVector.business_knowledge_id == business_knowledge_id,
                ChatbiBusinessKnowledgeVector.is_deleted.is_(False),
            )
            .values(is_deleted=True, updated_by=user_id)
        )
        await self._session.execute(stmt)

    async def soft_delete_by_business_knowledge_ids(
        self,
        *,
        record_ids: list[int],
        user_id: int | None,
    ) -> None:
        if not record_ids:
            return
        stmt = (
            update(ChatbiBusinessKnowledgeVector)
            .where(
                ChatbiBusinessKnowledgeVector.business_knowledge_id.in_(record_ids),
                ChatbiBusinessKnowledgeVector.is_deleted.is_(False),
            )
            .values(is_deleted=True, updated_by=user_id)
        )
        await self._session.execute(stmt)

    async def search_nearest_by_datasource(
        self,
        *,
        datasource_id: int,
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiBusinessKnowledgeSearchHit]:
        stmt = text(
            """
            SELECT business_knowledge_id,
                   1 - (v.embedding <=> CAST(:embedding AS vector)) AS score
            FROM ais_chatbi_business_knowledge_vector v
            JOIN ais_chatbi_business_knowledge b
              ON b.id = v.business_knowledge_id
            WHERE v.datasource_id = :datasource_id
              AND v.is_deleted = FALSE
              AND b.is_deleted = FALSE
              AND b.scope = :scope
            ORDER BY v.embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "datasource_id": datasource_id,
                "embedding": to_pgvector_literal(embedding),
                "scope": ChatbiBusinessKnowledgeScope.SYSTEM_INFERRED.value,
                "top_k": top_k,
            },
        )
        return [
            ChatbiBusinessKnowledgeSearchHit(
                business_knowledge_id=int(row["business_knowledge_id"]),
                score=float(row["score"]),
            )
            for row in result.mappings().all()
        ]


__all__ = ["ChatbiBusinessKnowledgeVectorRepository"]
