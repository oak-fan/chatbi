"""ChatBI 结构向量数据访问。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from cogmait_shared.core.id_generator import generate_snowflake_id

from ....domain.system.chatbi.vector import ChatbiSchemaSearchHit, ChatbiSchemaVectorRow
from ....models.system.chatbi import ChatbiSchemaVector
from .pgvector import to_pgvector_literal


class ChatbiSchemaVectorRepository:
    """封装 ais_chatbi_schema_vector 表的读写。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def soft_delete_by_datasource(self, datasource_id: int, *, user_id: int | None) -> None:
        stmt = (
            update(ChatbiSchemaVector)
            .where(
                ChatbiSchemaVector.datasource_id == datasource_id,
                ChatbiSchemaVector.is_deleted.is_(False),
            )
            .values(is_deleted=True, updated_by=user_id)
        )
        await self._session.execute(stmt)

    async def rebuild_vectors(
        self,
        *,
        datasource_id: int,
        rows: Sequence[ChatbiSchemaVectorRow],
        user_id: int | None,
    ) -> None:
        """软删旧向量后批量写入新列向量。"""
        await self.soft_delete_by_datasource(datasource_id, user_id=user_id)
        if not rows:
            return
        for row in rows:
            if int(row.datasource_id) != int(datasource_id):
                msg = "schema vector datasource_id 不一致"
                raise ValueError(msg)
        await self.bulk_insert_vectors(
            [
                (datasource_id, row.table_name, row.column_name, row.embedding, user_id)
                for row in rows
            ]
        )

    async def bulk_insert_vectors(
        self,
        rows: Sequence[tuple[int, str, str, list[float], int | None]],
    ) -> None:
        """批量插入列向量；rows 为 (datasource_id, table_name, column_name, embedding, user_id)。"""
        if not rows:
            return
        stmt = text(
            """
            INSERT INTO ais_chatbi_schema_vector (
                id,
                datasource_id,
                table_name,
                column_name,
                embedding,
                created_by,
                updated_by,
                is_deleted
            ) VALUES (
                :id,
                :datasource_id,
                :table_name,
                :column_name,
                CAST(:embedding AS vector),
                :user_id,
                :user_id,
                FALSE
            )
            """
        )
        await self._session.execute(
            stmt,
            [
                {
                    "id": generate_snowflake_id(),
                    "datasource_id": datasource_id,
                    "table_name": table_name,
                    "column_name": column_name,
                    "embedding": to_pgvector_literal(embedding),
                    "user_id": user_id,
                }
                for datasource_id, table_name, column_name, embedding, user_id in rows
            ],
        )

    async def search_nearest_by_datasource(
        self,
        datasource_id: int,
        embedding: list[float],
        top_k: int,
    ) -> list[ChatbiSchemaSearchHit]:
        """按 datasource_id 近邻检索列向量。"""
        stmt = text(
            """
            SELECT
                table_name,
                column_name,
                1 - (embedding <=> CAST(:embedding AS vector)) AS score
            FROM ais_chatbi_schema_vector
            WHERE datasource_id = :datasource_id
              AND is_deleted = FALSE
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
            ChatbiSchemaSearchHit(
                table_name=str(row["table_name"]),
                column_name=str(row["column_name"]),
                score=float(row["score"]),
            )
            for row in result.mappings().all()
        ]


__all__ = ["ChatbiSchemaVectorRepository"]
