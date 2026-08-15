"""ChatBI 问数日志数据访问。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....domain.system.chatbi.query_log import ChatbiQueryLogCreateInput, ChatbiQueryLogRecord
from ....models.system.chatbi import ChatbiQueryLog
from .mapping import require_datetime


def _to_record(entity: ChatbiQueryLog) -> ChatbiQueryLogRecord:
    return ChatbiQueryLogRecord(
        id=int(entity.id),
        assistant_message_id=int(entity.assistant_message_id),
        user_message_id=int(entity.user_message_id) if entity.user_message_id is not None else None,
        request_id=entity.request_id,
        datasource_id=int(entity.datasource_id) if entity.datasource_id is not None else None,
        user_question=entity.user_question,
        rewritten_question=entity.rewritten_question,
        intent=entity.intent,
        final_sql=entity.final_sql,
        result_preview=entity.result_preview,
        latency_ms=entity.latency_ms,
        meta=dict(entity.meta or {}),
        created_by=int(entity.created_by) if entity.created_by is not None else None,
        created_at=require_datetime(entity.created_at),
        updated_at=require_datetime(entity.updated_at),
    )


class ChatbiQueryLogRepository:
    """封装 ais_chatbi_query_log 表的读写。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, payload: ChatbiQueryLogCreateInput) -> int:
        entity = ChatbiQueryLog(
            assistant_message_id=payload.assistant_message_id,
            user_message_id=payload.user_message_id,
            request_id=payload.request_id,
            datasource_id=payload.datasource_id,
            user_question=payload.user_question,
            rewritten_question=payload.rewritten_question,
            intent=payload.intent,
            final_sql=payload.final_sql,
            result_preview=payload.result_preview,
            latency_ms=payload.latency_ms,
            meta=dict(payload.meta),
            created_by=payload.user_id,
            updated_by=payload.user_id,
        )
        self._session.add(entity)
        await self._session.flush()
        return int(entity.id)

    async def get_by_id(self, record_id: int) -> ChatbiQueryLogRecord | None:
        stmt = select(ChatbiQueryLog).where(
            ChatbiQueryLog.id == record_id,
            ChatbiQueryLog.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        entity = result.scalar_one_or_none()
        return _to_record(entity) if entity is not None else None

    async def get_by_assistant_message_id(
        self,
        assistant_message_id: int,
    ) -> ChatbiQueryLogRecord | None:
        stmt = select(ChatbiQueryLog).where(
            ChatbiQueryLog.assistant_message_id == assistant_message_id,
            ChatbiQueryLog.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        entity = result.scalar_one_or_none()
        return _to_record(entity) if entity is not None else None
