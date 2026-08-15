"""Agent-facing tools for the independent ChatBI multi-agent SQL flow."""

from __future__ import annotations

import os
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .....domain.system.chatbi.db_schema import ChatbiDbSchemaRecord
from .....domain.system.llm import EmbeddingRequest
from .....repositories.system.chatbi.pgvector import to_pgvector_literal
from ...llm_service import LLMService
from ..datasource.db_connection_service import ChatbiDbConnectionService
from ..query.prompts import json_safe_rows
from ..query.value_founding import (
    ValueFoundingLiteral,
    ValueFoundingMatcher,
)
from .types import KnowledgeSearchHit, SqlProbeResult

DEFAULT_KNOWLEDGE_DATABASE_URL = (
    "postgresql+asyncpg://postgres:123456@47.94.248.19:18004/postgres"
)
KNOWLEDGE_DATABASE_URL_ENV = "CHATBI_MULTI_AGENT_KNOWLEDGE_DATABASE_URL"
SHARED_KNOWLEDGE_DATABASE_URL_ENV = "CHATBI_KNOWLEDGE_DATABASE_URL"


class MultiAgentToolbox:
    """Small, JSON-friendly tool facade for multi-agent orchestration."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        db_connection: ChatbiDbConnectionService,
        datasource_id: int,
        datasource_owner_id: int | None,
        db_name: str,
        db_type: str,
        schema: ChatbiDbSchemaRecord,
        knowledge_database_url: str | None = None,
    ) -> None:
        self._llm = llm_service
        self._db = db_connection
        self._datasource_id = datasource_id
        self._datasource_owner_id = datasource_owner_id
        self._db_name = db_name
        self._db_type = db_type.upper()
        self._schema = schema
        self._knowledge_database_url = (
            knowledge_database_url
            or os.getenv(SHARED_KNOWLEDGE_DATABASE_URL_ENV)
            or os.getenv(KNOWLEDGE_DATABASE_URL_ENV)
            or DEFAULT_KNOWLEDGE_DATABASE_URL
        )
        self._knowledge_engine: AsyncEngine | None = None

    async def close(self) -> None:
        if self._knowledge_engine is not None:
            await self._knowledge_engine.dispose()
            self._knowledge_engine = None

    async def knowledge_search(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        """RAG search in the per-BIRD-database description knowledge store."""

        text_query = query.strip()
        if not text_query:
            return []
        embedding_resp = await self._llm.aembedding(EmbeddingRequest(input_texts=[text_query]))
        embedding = embedding_resp.embeddings[0]
        engine = self._get_knowledge_engine()
        stmt = text(
            """
            SELECT
                chunk_id,
                db_name,
                table_name,
                source_path,
                content,
                metadata,
                1 - (embedding <=> CAST(:embedding AS vector)) AS score
            FROM bird_dev_knowledge_chunks
            WHERE db_name = :db_name
            ORDER BY embedding <=> CAST(:embedding AS vector), chunk_id
            LIMIT :top_k
            """
        )
        async with engine.connect() as conn:
            result = await conn.execute(
                stmt,
                {
                    "db_name": self._db_name,
                    "embedding": to_pgvector_literal(embedding),
                    "top_k": max(1, int(top_k)),
                },
            )
            rows = result.mappings().all()
        hits = [
            KnowledgeSearchHit(
                chunk_id=str(row["chunk_id"]),
                db_name=str(row["db_name"]),
                table_name=str(row["table_name"]),
                source_path=str(row["source_path"]),
                content=str(row["content"]),
                score=float(row["score"] or 0.0),
                metadata=cast(dict[str, Any], row["metadata"] or {}),
            )
            for row in rows
        ]
        return [
            {
                "chunk_id": hit.chunk_id,
                "db_name": hit.db_name,
                "table_name": hit.table_name,
                "source_path": hit.source_path,
                "content": hit.content,
                "score": hit.score,
                "metadata": hit.metadata,
            }
            for hit in hits
        ]

    async def sql_probe(
        self,
        sql: str,
        *,
        mode: str = "query",
        max_rows: int = 30,
    ) -> dict[str, Any]:
        """Execute an agent-authored read-only SQL probe."""

        normalized_mode = (mode or "query").strip().lower()
        probe_sql = self._probe_sql(sql, mode=normalized_mode)
        try:
            if self._datasource_owner_id is None:
                columns, rows, truncated = await self._db.execute_readonly_sql_by_datasource(
                    datasource_id=self._datasource_id,
                    sql=probe_sql,
                    max_rows=max(1, int(max_rows)),
                )
            else:
                columns, rows, truncated = await self._db.execute_readonly_sql(
                    datasource_id=self._datasource_id,
                    user_id=self._datasource_owner_id,
                    sql=probe_sql,
                    max_rows=max(1, int(max_rows)),
                )
            result = SqlProbeResult(
                mode=normalized_mode,
                sql=probe_sql,
                success=True,
                columns=list(columns),
                rows=json_safe_rows(rows),
                row_count=len(rows),
                truncated=bool(truncated),
            )
        except Exception as exc:
            result = SqlProbeResult(
                mode=normalized_mode,
                sql=probe_sql,
                success=False,
                error=str(exc)[:2000],
            )
        return {
            "mode": result.mode,
            "sql": result.sql,
            "success": result.success,
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "error": result.error,
        }

    async def value_founding(
        self,
        *,
        table_name: str,
        column_name: str,
        literal: str,
        max_matches: int = 20,
    ) -> list[dict[str, Any]]:
        """Find similar cell values in a given table column."""

        column_ref = f"{table_name.strip()}.{column_name.strip()}"

        async def _execute(sql: str, max_rows: int) -> tuple[list[str], list[dict[str, Any]], bool]:
            if self._datasource_owner_id is None:
                return await self._db.execute_readonly_sql_by_datasource(
                    datasource_id=self._datasource_id,
                    sql=sql,
                    max_rows=max_rows,
                )
            return await self._db.execute_readonly_sql(
                datasource_id=self._datasource_id,
                user_id=self._datasource_owner_id,
                sql=sql,
                max_rows=max_rows,
            )

        matcher = ValueFoundingMatcher(
            execute_sql=_execute,
            max_matches_per_literal_column=max(1, int(max_matches)),
            max_matches_total=max(1, int(max_matches)),
        )
        matches = await matcher.find_matches(
            literals=[ValueFoundingLiteral(value=literal, columns=[column_ref])],
            schema=self._schema,
        )
        return [
            {
                "literal": match.literal,
                "column_ref": match.column_ref,
                "value": match.value,
                "score": match.score,
            }
            for match in matches
        ]

    def _probe_sql(self, sql: str, *, mode: str) -> str:
        cleaned = sql.strip().rstrip(";").strip()
        if mode == "explain":
            if self._db_type == "SQLITE":
                return f"EXPLAIN QUERY PLAN {cleaned}"
            return f"EXPLAIN {cleaned}"
        return cleaned

    def _get_knowledge_engine(self) -> AsyncEngine:
        if self._knowledge_engine is None:
            self._knowledge_engine = create_async_engine(self._knowledge_database_url)
        return self._knowledge_engine


__all__ = [
    "DEFAULT_KNOWLEDGE_DATABASE_URL",
    "KNOWLEDGE_DATABASE_URL_ENV",
    "MultiAgentToolbox",
]
