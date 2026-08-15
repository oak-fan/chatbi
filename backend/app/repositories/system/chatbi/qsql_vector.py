"""ChatBI Q-SQL 向量数据访问。"""

from __future__ import annotations

from sqlalchemy import bindparam, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from cogmait_shared.core.id_generator import generate_snowflake_id

from ....domain.system.chatbi.vector import ChatbiQsqlSearchHit
from ....models.system.chatbi import ChatbiQsqlVector
from .pgvector import to_pgvector_literal


class ChatbiQsqlVectorRepository:
    """封装 ais_chatbi_qsql_vector 表的读写。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_vector(
        self,
        *,
        qsql_id: int,
        datasource_id: int,
        embedding: list[float],
        user_id: int | None,
    ) -> None:
        await self.soft_delete_by_qsql_id(qsql_id=qsql_id, user_id=user_id)
        stmt = text(
            """
            INSERT INTO ais_chatbi_qsql_vector (
                id, qsql_id, datasource_id, embedding,
                created_by, updated_by, is_deleted
            ) VALUES (
                :id, :qsql_id, :datasource_id, CAST(:embedding AS vector),
                :user_id, :user_id, FALSE
            )
            """
        )
        await self._session.execute(
            stmt,
            {
                "id": generate_snowflake_id(),
                "qsql_id": qsql_id,
                "datasource_id": datasource_id,
                "embedding": to_pgvector_literal(embedding),
                "user_id": user_id,
            },
        )

    async def soft_delete_by_qsql_id(self, *, qsql_id: int, user_id: int | None) -> None:
        stmt = (
            update(ChatbiQsqlVector)
            .where(
                ChatbiQsqlVector.qsql_id == qsql_id,
                ChatbiQsqlVector.is_deleted.is_(False),
            )
            .values(is_deleted=True, updated_by=user_id)
        )
        await self._session.execute(stmt)

    async def soft_delete_by_datasource(self, *, datasource_id: int, user_id: int | None) -> None:
        stmt = (
            update(ChatbiQsqlVector)
            .where(
                ChatbiQsqlVector.datasource_id == datasource_id,
                ChatbiQsqlVector.is_deleted.is_(False),
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
    ) -> list[ChatbiQsqlSearchHit]:
        stmt = text(
            """
            SELECT qsql_id, 1 - (embedding <=> CAST(:embedding AS vector)) AS score
            FROM ais_chatbi_qsql_vector
            WHERE datasource_id = :datasource_id AND is_deleted = FALSE
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "datasource_id": datasource_id,
                "embedding": to_pgvector_literal(embedding),
                "top_k": top_k,
            },
        )
        return [
            ChatbiQsqlSearchHit(qsql_id=int(row["qsql_id"]), score=float(row["score"]))
            for row in result.mappings().all()
        ]

    async def search_nearest_by_datasources(
        self,
        *,
        datasource_ids: list[int],
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiQsqlSearchHit]:
        ids = sorted({int(item) for item in datasource_ids})
        if not ids:
            return []
        stmt = text(
            """
            SELECT qsql_id, 1 - (embedding <=> CAST(:embedding AS vector)) AS score
            FROM ais_chatbi_qsql_vector
            WHERE datasource_id IN :datasource_ids AND is_deleted = FALSE
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
            """
        ).bindparams(bindparam("datasource_ids", expanding=True))
        result = await self._session.execute(
            stmt,
            {
                "datasource_ids": ids,
                "embedding": to_pgvector_literal(embedding),
                "top_k": top_k,
            },
        )
        return [
            ChatbiQsqlSearchHit(qsql_id=int(row["qsql_id"]), score=float(row["score"]))
            for row in result.mappings().all()
        ]


__all__ = ["ChatbiQsqlVectorRepository"]
