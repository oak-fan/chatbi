"""ChatBI 数据源数据访问。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....constants.chatbi.datasource import CHATBI_DEFAULT_SCHEMA_NAME
from ....domain.system.chatbi import (
    ChatbiDatasourceConnectionRecord,
    ChatbiDatasourceCreateInput,
    ChatbiDatasourceFileUploadCreateInput,
    ChatbiDatasourceListParams,
    ChatbiDatasourceRecord,
    ChatbiDatasourceUpdateInput,
    DataSourceOrigin,
    DataSourceType,
)
from ....models.system.chatbi import ChatbiDatasource
from ...base_mapper import BaseRepositoryMapper
from ...utils import escape_like
from .mapping import require_datetime

DATASOURCE_CREATE_FIELDS = (
    "name",
    "connector_type",
    "host",
    "port",
    "database",
    "schema_name",
    "username",
    "extra_params",
    "remark",
)
DATASOURCE_FILE_UPLOAD_CREATE_FIELDS = (
    "name",
    "host",
    "port",
    "database",
    "schema_name",
    "username",
    "extra_params",
    "remark",
)
DATASOURCE_UPDATE_VALUE_FIELDS = (
    "name",
    "host",
    "port",
    "database",
    "username",
)
DATASOURCE_UPDATE_PATCH_FIELDS = (
    "schema_name",
    "extra_params",
    "remark",
)


def _to_record(entity: ChatbiDatasource) -> ChatbiDatasourceRecord:
    return ChatbiDatasourceRecord(
        id=int(entity.id),
        origin=entity.origin,
        name=entity.name,
        connector_type=entity.connector_type,
        host=entity.host,
        port=int(entity.port),
        database=entity.database,
        schema_name=entity.schema_name,
        username=entity.username,
        import_file_ids=list(entity.import_file_ids or []),
        db_schema=entity.db_schema,
        db_schema_updated_at=entity.db_schema_updated_at,
        extra_params=entity.extra_params,
        remark=entity.remark,
        created_at=require_datetime(entity.created_at),
        updated_at=require_datetime(entity.updated_at),
    )


def _to_connection_record(entity: ChatbiDatasource) -> ChatbiDatasourceConnectionRecord:
    return ChatbiDatasourceConnectionRecord(
        id=int(entity.id),
        connector_type=entity.connector_type,
        host=entity.host,
        port=int(entity.port),
        database=entity.database,
        schema_name=entity.schema_name,
        username=entity.username,
        encrypted_password=entity.password,
        extra_params=entity.extra_params,
    )


class ChatbiDatasourceRepository:
    """封装 ais_chatbi_datasource 表的读写。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        payload: ChatbiDatasourceCreateInput,
        *,
        encrypted_password: str,
    ) -> int:
        data = BaseRepositoryMapper.to_kwargs(payload, DATASOURCE_CREATE_FIELDS)
        data["schema_name"] = (
            payload.schema_name or CHATBI_DEFAULT_SCHEMA_NAME
            if payload.connector_type == DataSourceType.POSTGRESQL.value
            else payload.schema_name
        )
        data["extra_params"] = dict(payload.extra_params or {})
        entity = ChatbiDatasource(
            origin=DataSourceOrigin.EXTERNAL.value,
            password=encrypted_password,
            import_file_ids=None,
            db_schema=None,
            db_schema_updated_at=None,
            created_by=payload.user_id,
            updated_by=payload.user_id,
            **data,
        )
        self._session.add(entity)
        await self._session.flush()
        return int(entity.id)

    async def create_file_upload(
        self,
        payload: ChatbiDatasourceFileUploadCreateInput,
    ) -> int:
        data = BaseRepositoryMapper.to_kwargs(payload, DATASOURCE_FILE_UPLOAD_CREATE_FIELDS)
        data["extra_params"] = dict(payload.extra_params or {})
        entity = ChatbiDatasource(
            origin=DataSourceOrigin.FILE_UPLOAD.value,
            connector_type=DataSourceType.POSTGRESQL.value,
            password=payload.encrypted_password,
            import_file_ids=list(payload.file_ids),
            db_schema=None,
            db_schema_updated_at=None,
            created_by=payload.user_id,
            updated_by=payload.user_id,
            **data,
        )
        self._session.add(entity)
        await self._session.flush()
        return int(entity.id)

    async def get_by_id(self, datasource_id: int) -> ChatbiDatasourceRecord | None:
        stmt = select(ChatbiDatasource).where(
            ChatbiDatasource.id == datasource_id,
            ChatbiDatasource.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        entity = result.scalar_one_or_none()
        return _to_record(entity) if entity is not None else None

    async def get_active_by_name_for_user(
        self,
        name: str,
        user_id: int,
    ) -> ChatbiDatasourceRecord | None:
        stmt = (
            select(ChatbiDatasource)
            .where(
                ChatbiDatasource.name == name,
                ChatbiDatasource.created_by == user_id,
                ChatbiDatasource.is_deleted.is_(False),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        entity = result.scalar_one_or_none()
        return _to_record(entity) if entity is not None else None

    async def _fetch_entity_for_user(
        self,
        datasource_id: int,
        user_id: int,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> ChatbiDatasource | None:
        stmt = select(ChatbiDatasource).where(
            ChatbiDatasource.id == datasource_id,
            ChatbiDatasource.created_by == user_id,
        )
        if not include_deleted:
            stmt = stmt.where(ChatbiDatasource.is_deleted.is_(False))
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_user(
        self,
        datasource_id: int,
        user_id: int,
        *,
        include_deleted: bool = False,
        for_update: bool = False,
    ) -> ChatbiDatasourceRecord | None:
        entity = await self._fetch_entity_for_user(
            datasource_id,
            user_id,
            include_deleted=include_deleted,
            for_update=for_update,
        )
        return _to_record(entity) if entity is not None else None

    async def get_connection_for_user(
        self,
        datasource_id: int,
        user_id: int,
    ) -> ChatbiDatasourceConnectionRecord | None:
        stmt = select(ChatbiDatasource).where(
            ChatbiDatasource.id == datasource_id,
            ChatbiDatasource.created_by == user_id,
            ChatbiDatasource.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        entity = result.scalar_one_or_none()
        return _to_connection_record(entity) if entity is not None else None

    async def get_connection_by_id(
        self,
        datasource_id: int,
    ) -> ChatbiDatasourceConnectionRecord | None:
        stmt = select(ChatbiDatasource).where(
            ChatbiDatasource.id == datasource_id,
            ChatbiDatasource.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        entity = result.scalar_one_or_none()
        return _to_connection_record(entity) if entity is not None else None

    async def get_owner_id(self, datasource_id: int) -> int | None:
        stmt = select(ChatbiDatasource.created_by).where(
            ChatbiDatasource.id == datasource_id,
            ChatbiDatasource.is_deleted.is_(False),
        )
        value = (await self._session.execute(stmt)).scalar_one_or_none()
        return int(value) if value is not None else None

    async def list_for_user(
        self,
        params: ChatbiDatasourceListParams,
    ) -> tuple[list[ChatbiDatasourceRecord], int]:
        filters = [
            ChatbiDatasource.is_deleted.is_(False),
            ChatbiDatasource.created_by == params.user_id,
        ]
        if params.name_keyword:
            kw = f"%{escape_like(params.name_keyword)}%"
            filters.append(
                or_(
                    ChatbiDatasource.name.like(kw, escape="\\"),
                    ChatbiDatasource.remark.like(kw, escape="\\"),
                )
            )
        if params.connector_type_filter:
            filters.append(ChatbiDatasource.connector_type == params.connector_type_filter)

        base = select(ChatbiDatasource).where(*filters)
        count_stmt = select(func.count()).select_from(base.subquery())
        total = int((await self._session.execute(count_stmt)).scalar_one() or 0)
        stmt = (
            base.order_by(ChatbiDatasource.updated_at.desc(), ChatbiDatasource.id.desc())
            .offset((params.page - 1) * params.size)
            .limit(params.size)
        )
        rows = await self._session.execute(stmt)
        return [_to_record(entity) for entity in rows.scalars().all()], total

    async def list_ready_for_user(
        self,
        *,
        user_id: int,
        limit: int,
    ) -> list[ChatbiDatasourceRecord]:
        stmt = (
            select(ChatbiDatasource)
            .where(
                ChatbiDatasource.is_deleted.is_(False),
                ChatbiDatasource.created_by == user_id,
                ChatbiDatasource.db_schema.is_not(None),
            )
            .order_by(ChatbiDatasource.updated_at.desc(), ChatbiDatasource.id.desc())
            .limit(limit)
        )
        rows = await self._session.execute(stmt)
        return [_to_record(entity) for entity in rows.scalars().all()]

    async def update_for_user(
        self,
        datasource_id: int,
        user_id: int,
        payload: ChatbiDatasourceUpdateInput,
        *,
        encrypted_password: str | None,
    ) -> bool:
        entity = await self._fetch_entity_for_user(datasource_id, user_id, for_update=True)
        if entity is None:
            return False
        for field in DATASOURCE_UPDATE_VALUE_FIELDS:
            if field not in payload.provided_fields:
                continue
            value = getattr(payload, field)
            if value is not None:
                setattr(entity, field, value)
        for field in DATASOURCE_UPDATE_PATCH_FIELDS:
            if field not in payload.provided_fields:
                continue
            value = getattr(payload, field)
            if field == "extra_params":
                value = dict(value or {})
            setattr(entity, field, value)
        if encrypted_password is not None:
            entity.password = encrypted_password
        entity.updated_by = user_id
        await self._session.flush()
        return True

    async def soft_delete(self, datasource_id: int, user_id: int) -> bool:
        entity = await self._fetch_entity_for_user(datasource_id, user_id, for_update=True)
        if entity is None:
            return False
        entity.is_deleted = True
        entity.updated_by = user_id
        await self._session.flush()
        return True

    async def update_schema_name(
        self,
        datasource_id: int,
        schema_name: str,
        *,
        user_id: int,
    ) -> None:
        entity = await self._fetch_entity_for_user(datasource_id, user_id, for_update=True)
        if entity is None:
            return
        entity.schema_name = schema_name
        entity.updated_by = user_id
        await self._session.flush()

    async def update_db_schema(
        self,
        datasource_id: int,
        *,
        db_schema: dict[str, Any],
        updated_by: int | None,
    ) -> None:
        now = datetime.now().astimezone()
        stmt = (
            update(ChatbiDatasource)
            .where(ChatbiDatasource.id == datasource_id, ChatbiDatasource.is_deleted.is_(False))
            .values(
                db_schema=db_schema,
                db_schema_updated_at=now,
                updated_by=updated_by,
                updated_at=now,
            )
        )
        await self._session.execute(stmt)

    async def clear_db_schema(
        self,
        datasource_id: int,
        *,
        updated_by: int | None,
    ) -> None:
        now = datetime.now().astimezone()
        stmt = (
            update(ChatbiDatasource)
            .where(ChatbiDatasource.id == datasource_id, ChatbiDatasource.is_deleted.is_(False))
            .values(
                db_schema=None,
                db_schema_updated_at=None,
                updated_by=updated_by,
                updated_at=now,
            )
        )
        await self._session.execute(stmt)
