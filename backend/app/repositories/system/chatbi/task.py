"""ChatBI 任务数据访问。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....domain.system.chatbi import ACTIVE_TASK_STATUSES, ChatbiTaskRecord, TaskStatus
from ....models.system.chatbi import ChatbiDatasource, ChatbiTask
from ...base_mapper import BaseRepositoryMapper

TASK_DETAIL_FIELDS = (
    "id",
    "task_type",
    "status",
    "datasource_id",
    "total_count",
    "processed_count",
    "payload",
    "last_error",
    "created_by",
)


def _to_record(entity: ChatbiTask) -> ChatbiTaskRecord:
    payload = BaseRepositoryMapper.to_kwargs(entity, TASK_DETAIL_FIELDS)
    payload["id"] = int(entity.id)
    payload["datasource_id"] = int(entity.datasource_id)
    payload["total_count"] = int(entity.total_count)
    payload["processed_count"] = int(entity.processed_count)
    payload["payload"] = dict(entity.payload or {})
    return ChatbiTaskRecord(**payload)


class ChatbiTaskRepository:
    """封装 ais_chatbi_task 表的读写。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def has_active_task(self, datasource_id: int) -> bool:
        stmt = (
            select(func.count())
            .select_from(ChatbiTask)
            .where(
                ChatbiTask.datasource_id == datasource_id,
                ChatbiTask.is_deleted.is_(False),
                ChatbiTask.status.in_(ACTIVE_TASK_STATUSES),
            )
        )
        n = int((await self._session.execute(stmt)).scalar_one() or 0)
        return n > 0

    async def create_task(
        self,
        *,
        datasource_id: int,
        task_type: str,
        user_id: int,
        payload: dict[str, Any] | None = None,
        total_count: int = 1,
    ) -> int:
        entity = ChatbiTask(
            task_type=task_type,
            status=TaskStatus.PENDING.value,
            datasource_id=datasource_id,
            total_count=total_count,
            processed_count=0,
            payload=dict(payload or {}),
            last_error=None,
            created_by=user_id,
            updated_by=user_id,
        )
        self._session.add(entity)
        await self._session.flush()
        return int(entity.id)

    async def _fetch_task_for_update(self, task_id: int) -> ChatbiTask | None:
        stmt = (
            select(ChatbiTask)
            .where(ChatbiTask.id == task_id, ChatbiTask.is_deleted.is_(False))
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_task_for_update(self, task_id: int) -> ChatbiTaskRecord | None:
        entity = await self._fetch_task_for_update(task_id)
        return _to_record(entity) if entity is not None else None

    async def mark_running(self, task_id: int, *, user_id: int | None) -> bool:
        task = await self._fetch_task_for_update(task_id)
        if task is None:
            return False
        task.status = TaskStatus.RUNNING.value
        task.updated_by = user_id
        await self._session.flush()
        return True

    async def mark_success(self, task_id: int, *, user_id: int | None) -> bool:
        task = await self._fetch_task_for_update(task_id)
        if task is None:
            return False
        task.status = TaskStatus.SUCCESS.value
        task.processed_count = task.total_count
        task.updated_by = user_id
        await self._session.flush()
        return True

    async def mark_failed(self, task_id: int, message: str, *, user_id: int | None) -> bool:
        task = await self._fetch_task_for_update(task_id)
        if task is None:
            return False
        task.status = TaskStatus.FAILED.value
        task.last_error = message[:4000]
        task.updated_by = user_id
        await self._session.flush()
        return True

    async def verify_datasource_owned(self, datasource_id: int, user_id: int) -> bool:
        stmt = (
            select(func.count())
            .select_from(ChatbiDatasource)
            .where(
                ChatbiDatasource.id == datasource_id,
                ChatbiDatasource.created_by == user_id,
                ChatbiDatasource.is_deleted.is_(False),
            )
        )
        n = int((await self._session.execute(stmt)).scalar_one() or 0)
        return n > 0

    async def set_processed(
        self,
        task_id: int,
        processed: int,
        *,
        user_id: int | None,
    ) -> bool:
        task = await self._fetch_task_for_update(task_id)
        if task is None:
            return False
        task.processed_count = processed
        task.updated_by = user_id
        await self._session.flush()
        return True

    async def fail_publish(self, task_id: int, message: str) -> None:
        stmt = (
            update(ChatbiTask)
            .where(ChatbiTask.id == task_id, ChatbiTask.is_deleted.is_(False))
            .values(
                status=TaskStatus.FAILED.value,
                last_error=message[:4000],
            )
        )
        await self._session.execute(stmt)
