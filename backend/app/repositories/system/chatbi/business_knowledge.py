"""ChatBI 业务知识数据访问。"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from ....domain.system.chatbi import (
    ChatbiBusinessKnowledgeCreateInput,
    ChatbiBusinessKnowledgeListParams,
    ChatbiBusinessKnowledgeRecord,
    ChatbiBusinessKnowledgeUpdateInput,
)
from ....models.system.chatbi import ChatbiBusinessKnowledge, ChatbiDatasource
from ...base_mapper import BaseRepositoryMapper
from .mapping import require_datetime

BUSINESS_KNOWLEDGE_CREATE_FIELDS = (
    "content",
    "scope",
    "kind",
    "datasource_id",
)
BUSINESS_KNOWLEDGE_UPDATE_FIELDS = BUSINESS_KNOWLEDGE_CREATE_FIELDS


def _to_record(entity: ChatbiBusinessKnowledge) -> ChatbiBusinessKnowledgeRecord:
    return ChatbiBusinessKnowledgeRecord(
        id=int(entity.id),
        content=entity.content,
        scope=entity.scope,
        kind=entity.kind,
        datasource_id=int(entity.datasource_id),
        created_at=require_datetime(entity.created_at),
        updated_at=require_datetime(entity.updated_at),
    )


class ChatbiBusinessKnowledgeRepository:
    """封装 ais_chatbi_business_knowledge 表的读写。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, payload: ChatbiBusinessKnowledgeCreateInput) -> int:
        entity = ChatbiBusinessKnowledge(
            created_by=payload.user_id,
            updated_by=payload.user_id,
            **BaseRepositoryMapper.to_kwargs(payload, BUSINESS_KNOWLEDGE_CREATE_FIELDS),
        )
        self._session.add(entity)
        await self._session.flush()
        return int(entity.id)

    async def _fetch_by_id(
        self,
        record_id: int,
        *,
        for_update: bool = False,
    ) -> ChatbiBusinessKnowledge | None:
        stmt = select(ChatbiBusinessKnowledge).where(
            ChatbiBusinessKnowledge.id == record_id,
            ChatbiBusinessKnowledge.is_deleted.is_(False),
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, record_id: int) -> ChatbiBusinessKnowledgeRecord | None:
        entity = await self._fetch_by_id(record_id)
        return _to_record(entity) if entity is not None else None

    async def _fetch_for_user(
        self,
        record_id: int,
        user_id: int,
        *,
        for_update: bool = False,
    ) -> ChatbiBusinessKnowledge | None:
        stmt = (
            select(ChatbiBusinessKnowledge)
            .join(ChatbiDatasource, ChatbiDatasource.id == ChatbiBusinessKnowledge.datasource_id)
            .where(
                ChatbiBusinessKnowledge.id == record_id,
                ChatbiBusinessKnowledge.is_deleted.is_(False),
                ChatbiDatasource.created_by == user_id,
                ChatbiDatasource.is_deleted.is_(False),
            )
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_user(
        self,
        record_id: int,
        user_id: int,
    ) -> ChatbiBusinessKnowledgeRecord | None:
        entity = await self._fetch_for_user(record_id, user_id)
        return _to_record(entity) if entity is not None else None

    async def list_paginated(
        self,
        params: ChatbiBusinessKnowledgeListParams,
    ) -> tuple[list[ChatbiBusinessKnowledgeRecord], int]:
        filters: list[ColumnElement[bool]] = [
            ChatbiBusinessKnowledge.is_deleted.is_(False),
            ChatbiDatasource.created_by == params.user_id,
            ChatbiDatasource.is_deleted.is_(False),
        ]
        if params.scope:
            filters.append(ChatbiBusinessKnowledge.scope == params.scope)
        if params.kind:
            filters.append(ChatbiBusinessKnowledge.kind == params.kind)
        if params.datasource_id is not None:
            filters.append(ChatbiBusinessKnowledge.datasource_id == params.datasource_id)
        base = (
            select(ChatbiBusinessKnowledge)
            .join(ChatbiDatasource, ChatbiDatasource.id == ChatbiBusinessKnowledge.datasource_id)
            .where(*filters)
        )
        count_stmt = select(func.count()).select_from(base.subquery())
        total = int((await self._session.execute(count_stmt)).scalar_one() or 0)
        stmt = (
            base.order_by(
                ChatbiBusinessKnowledge.updated_at.desc(),
                ChatbiBusinessKnowledge.id.desc(),
            )
            .offset((params.page - 1) * params.size)
            .limit(params.size)
        )
        rows = await self._session.execute(stmt)
        return [_to_record(entity) for entity in rows.scalars().all()], total

    async def update(self, payload: ChatbiBusinessKnowledgeUpdateInput) -> bool:
        entity = await self._fetch_for_user(
            payload.record_id,
            payload.user_id,
            for_update=True,
        )
        if entity is None:
            return False
        for field in BUSINESS_KNOWLEDGE_UPDATE_FIELDS:
            if field not in payload.provided_fields:
                continue
            value = getattr(payload, field)
            if value is not None:
                setattr(entity, field, value)
        entity.updated_by = payload.user_id
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
            select(ChatbiBusinessKnowledge.id)
            .join(ChatbiDatasource, ChatbiDatasource.id == ChatbiBusinessKnowledge.datasource_id)
            .where(
                ChatbiBusinessKnowledge.datasource_id == datasource_id,
                ChatbiBusinessKnowledge.is_deleted.is_(False),
                ChatbiDatasource.created_by == user_id,
                ChatbiDatasource.is_deleted.is_(False),
            )
        )
        record_ids = [int(row) for row in (await self._session.execute(stmt)).scalars().all()]
        if not record_ids:
            return []
        await self._session.execute(
            update(ChatbiBusinessKnowledge)
            .where(ChatbiBusinessKnowledge.id.in_(record_ids))
            .values(is_deleted=True, updated_by=user_id)
        )
        await self._session.flush()
        return record_ids

    async def list_by_datasource_and_scope(
        self,
        datasource_id: int,
        scope: str,
        *,
        limit: int | None = None,
    ) -> list[ChatbiBusinessKnowledgeRecord]:
        stmt = (
            select(ChatbiBusinessKnowledge)
            .where(
                ChatbiBusinessKnowledge.datasource_id == datasource_id,
                ChatbiBusinessKnowledge.scope == scope,
                ChatbiBusinessKnowledge.is_deleted.is_(False),
            )
            .order_by(
                ChatbiBusinessKnowledge.updated_at.desc(),
                ChatbiBusinessKnowledge.id.desc(),
            )
        )
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [_to_record(entity) for entity in result.scalars().all()]

    async def filter_ids_by_datasource(
        self,
        record_ids: list[int],
        datasource_id: int,
    ) -> list[int]:
        if not record_ids:
            return []
        stmt = select(ChatbiBusinessKnowledge.id).where(
            ChatbiBusinessKnowledge.id.in_(record_ids),
            ChatbiBusinessKnowledge.is_deleted.is_(False),
            ChatbiBusinessKnowledge.datasource_id == datasource_id,
        )
        result = await self._session.execute(stmt)
        return [int(row[0]) for row in result.all()]
