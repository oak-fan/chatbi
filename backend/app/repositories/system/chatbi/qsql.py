"""ChatBI Q-SQL 数据访问。"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from ....domain.system.chatbi import (
    QSQL_SCOPE_GLOBAL,
    ChatbiQsqlCreateInput,
    ChatbiQsqlListParams,
    ChatbiQsqlRecord,
    ChatbiQsqlUpdateInput,
)
from ....models.system.chatbi import ChatbiDatasource, ChatbiQsql
from ...base_mapper import BaseRepositoryMapper
from .mapping import require_datetime

QSQL_CREATE_FIELDS = (
    "datasource_id",
    "question",
    "sql_body",
    "scope",
    "source_dataset",
    "source_db_id",
    "source_sample_id",
    "sql_skeleton",
)
QSQL_UPDATE_FIELDS = (
    "question",
    "sql_body",
)


def _to_record(entity: ChatbiQsql) -> ChatbiQsqlRecord:
    return ChatbiQsqlRecord(
        id=int(entity.id),
        datasource_id=int(entity.datasource_id),
        question=entity.question,
        sql_body=entity.sql_body,
        llm_simplified_description=entity.llm_simplified_description,
        scope=entity.scope,
        source_dataset=entity.source_dataset,
        source_db_id=entity.source_db_id,
        source_sample_id=entity.source_sample_id,
        sql_skeleton=entity.sql_skeleton,
        created_at=require_datetime(entity.created_at),
        updated_at=require_datetime(entity.updated_at),
    )


class ChatbiQsqlRepository:
    """封装 ais_chatbi_qsql 表的读写。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, payload: ChatbiQsqlCreateInput) -> int:
        entity = ChatbiQsql(
            llm_simplified_description=None,
            created_by=payload.user_id,
            updated_by=payload.user_id,
            **BaseRepositoryMapper.to_kwargs(payload, QSQL_CREATE_FIELDS),
        )
        self._session.add(entity)
        await self._session.flush()
        return int(entity.id)

    async def _fetch_by_id(
        self,
        record_id: int,
        *,
        for_update: bool = False,
    ) -> ChatbiQsql | None:
        stmt = select(ChatbiQsql).where(
            ChatbiQsql.id == record_id,
            ChatbiQsql.is_deleted.is_(False),
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, record_id: int) -> ChatbiQsqlRecord | None:
        entity = await self._fetch_by_id(record_id)
        return _to_record(entity) if entity is not None else None

    async def get_global_by_source_sample(
        self,
        *,
        source_dataset: str,
        source_sample_id: str,
    ) -> ChatbiQsqlRecord | None:
        stmt = select(ChatbiQsql).where(
            ChatbiQsql.scope == QSQL_SCOPE_GLOBAL,
            ChatbiQsql.source_dataset == source_dataset,
            ChatbiQsql.source_sample_id == source_sample_id,
            ChatbiQsql.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        entity = result.scalar_one_or_none()
        return _to_record(entity) if entity is not None else None

    async def list_existing_global_source_sample_ids(
        self,
        *,
        source_dataset: str,
        source_sample_ids: list[str],
    ) -> set[str]:
        if not source_sample_ids:
            return set()
        stmt = select(ChatbiQsql.source_sample_id).where(
            ChatbiQsql.scope == QSQL_SCOPE_GLOBAL,
            ChatbiQsql.source_dataset == source_dataset,
            ChatbiQsql.source_sample_id.in_(source_sample_ids),
            ChatbiQsql.is_deleted.is_(False),
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return {str(item) for item in rows if item is not None}

    async def _fetch_for_user(
        self,
        record_id: int,
        user_id: int,
        *,
        for_update: bool = False,
    ) -> ChatbiQsql | None:
        stmt = (
            select(ChatbiQsql)
            .join(ChatbiDatasource, ChatbiDatasource.id == ChatbiQsql.datasource_id)
            .where(
                ChatbiQsql.id == record_id,
                ChatbiQsql.is_deleted.is_(False),
                ChatbiDatasource.created_by == user_id,
                ChatbiDatasource.is_deleted.is_(False),
            )
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_user(self, record_id: int, user_id: int) -> ChatbiQsqlRecord | None:
        entity = await self._fetch_for_user(record_id, user_id)
        return _to_record(entity) if entity is not None else None

    async def list_paginated(
        self,
        params: ChatbiQsqlListParams,
    ) -> tuple[list[ChatbiQsqlRecord], int]:
        filters: list[ColumnElement[bool]] = [
            ChatbiQsql.is_deleted.is_(False),
            ChatbiDatasource.created_by == params.user_id,
            ChatbiDatasource.is_deleted.is_(False),
        ]
        if params.datasource_id is not None:
            filters.append(ChatbiQsql.datasource_id == params.datasource_id)
        base = (
            select(ChatbiQsql)
            .join(ChatbiDatasource, ChatbiDatasource.id == ChatbiQsql.datasource_id)
            .where(*filters)
        )
        count_stmt = select(func.count()).select_from(base.subquery())
        total = int((await self._session.execute(count_stmt)).scalar_one() or 0)
        stmt = (
            base.order_by(ChatbiQsql.updated_at.desc(), ChatbiQsql.id.desc())
            .offset((params.page - 1) * params.size)
            .limit(params.size)
        )
        rows = await self._session.execute(stmt)
        return [_to_record(entity) for entity in rows.scalars().all()], total

    async def update(self, payload: ChatbiQsqlUpdateInput) -> bool:
        entity = await self._fetch_for_user(
            payload.record_id,
            payload.user_id,
            for_update=True,
        )
        if entity is None:
            return False
        for field in QSQL_UPDATE_FIELDS:
            if field not in payload.provided_fields:
                continue
            value = getattr(payload, field)
            if value is not None:
                setattr(entity, field, value)
        entity.updated_by = payload.user_id
        await self._session.flush()
        return True

    async def update_description(
        self,
        record_id: int,
        *,
        description: str | None,
        user_id: int,
    ) -> bool:
        entity = await self._fetch_for_user(record_id, user_id, for_update=True)
        if entity is None:
            return False
        entity.llm_simplified_description = description
        entity.updated_by = user_id
        await self._session.flush()
        return True

    async def soft_delete(self, record_id: int, user_id: int) -> bool:
        entity = await self._fetch_for_user(record_id, user_id, for_update=True)
        if entity is None:
            return False
        entity.is_deleted = True
        entity.updated_by = user_id
        await self._session.flush()
        return True

    async def soft_delete_by_datasource(self, datasource_id: int, user_id: int) -> list[int]:
        """按数据源批量逻辑删除，返回已删除记录 ID。"""
        stmt = (
            select(ChatbiQsql.id)
            .join(ChatbiDatasource, ChatbiDatasource.id == ChatbiQsql.datasource_id)
            .where(
                ChatbiQsql.datasource_id == datasource_id,
                ChatbiQsql.is_deleted.is_(False),
                ChatbiDatasource.created_by == user_id,
                ChatbiDatasource.is_deleted.is_(False),
            )
        )
        record_ids = [int(row) for row in (await self._session.execute(stmt)).scalars().all()]
        if not record_ids:
            return []
        await self._session.execute(
            update(ChatbiQsql)
            .where(ChatbiQsql.id.in_(record_ids))
            .values(is_deleted=True, updated_by=user_id)
        )
        await self._session.flush()
        return record_ids
