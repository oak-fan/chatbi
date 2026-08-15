"""Chat 数据访问。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...constants.chat import (
    CHAT_DEFAULT_APP_NAME,
    CHAT_DEFAULT_TOP_K,
    CHAT_FILE_PARSE_STATUS_FAILED,
    CHAT_FILE_PARSE_STATUS_SUCCESS,
    CHAT_RUN_MODE_AUTO,
    CHAT_SESSION_SOURCE_CHAT,
    CHAT_SESSION_SOURCE_PUBLIC_SHARE,
)
from ...domain.system.chat import ChatMessageRole, ChatMessageStatus
from ...models.system.chat import (
    ChatApp,
    ChatAppShare,
    ChatAppVersion,
    ChatFeedback,
    ChatFeedbackType,
    ChatFileChunk,
    ChatFileContext,
    ChatMessage,
    ChatProject,
    ChatSession,
)


class ChatRepository:
    """封装 Chat 相关表的读写。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_chat_app(self, chat_app_id: int) -> ChatApp | None:
        stmt = select(ChatApp).where(ChatApp.id == chat_app_id, ChatApp.is_deleted.is_(False))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_chat_app_version(
        self,
        version_id: int,
        *,
        chat_app_id: int | None = None,
    ) -> ChatAppVersion | None:
        conditions: list[Any] = [
            ChatAppVersion.id == version_id,
            ChatAppVersion.is_deleted.is_(False),
        ]
        if chat_app_id is not None:
            conditions.append(ChatAppVersion.chat_app_id == chat_app_id)
        stmt = select(ChatAppVersion).where(*conditions)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_current_chat_app_version(self, chat_app_id: int) -> ChatAppVersion | None:
        stmt = (
            select(ChatAppVersion)
            .where(
                ChatAppVersion.chat_app_id == chat_app_id,
                ChatAppVersion.is_current.is_(True),
                ChatAppVersion.is_deleted.is_(False),
            )
            .order_by(ChatAppVersion.version_no.desc(), ChatAppVersion.id.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_chat_app_by_name(
        self,
        name: str,
        *,
        exclude_id: int | None = None,
    ) -> ChatApp | None:
        conditions: list[Any] = [ChatApp.name == name, ChatApp.is_deleted.is_(False)]
        if exclude_id is not None:
            conditions.append(ChatApp.id != exclude_id)
        stmt = select(ChatApp).where(*conditions)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_chat_app_share(
        self,
        share_id: int,
        *,
        chat_app_id: int | None = None,
        for_update: bool = False,
    ) -> ChatAppShare | None:
        conditions: list[Any] = [
            ChatAppShare.id == share_id,
            ChatAppShare.is_deleted.is_(False),
        ]
        if chat_app_id is not None:
            conditions.append(ChatAppShare.chat_app_id == chat_app_id)
        stmt = select(ChatAppShare).where(*conditions)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_chat_app_share_by_token_hash(
        self,
        share_token_hash: str,
        *,
        for_update: bool = False,
    ) -> ChatAppShare | None:
        stmt = select(ChatAppShare).where(
            ChatAppShare.share_token_hash == share_token_hash,
            ChatAppShare.is_deleted.is_(False),
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_default_chat_app(self) -> ChatApp | None:
        stmt = (
            select(ChatApp)
            .where(
                ChatApp.is_default.is_(True),
                ChatApp.is_enabled.is_(True),
                ChatApp.is_deleted.is_(False),
            )
            .order_by(ChatApp.id.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_default_chat_app(self, *, user_id: int | None) -> ChatApp:
        now = datetime.now().astimezone()
        entity = ChatApp(
            name=CHAT_DEFAULT_APP_NAME,
            description=None,
            run_mode=CHAT_RUN_MODE_AUTO,
            knowledge_ids_json=[],
            system_prompt=None,
            completion_model=None,
            temperature=None,
            top_k=CHAT_DEFAULT_TOP_K,
            score_threshold=None,
            retrieval_strategy="HYBRID_RRF",
            retrieval_config_json={},
            is_enabled=True,
            is_default=True,
            draft_updated_at=now,
            created_by=user_id,
            updated_by=user_id,
        )
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def list_chat_apps(
        self,
        *,
        keyword: str | None,
        is_enabled: bool | None,
        page: int,
        size: int,
    ) -> tuple[list[ChatApp], int]:
        conditions: list[Any] = [ChatApp.is_deleted.is_(False)]
        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(
                or_(
                    ChatApp.name.ilike(pattern),
                    ChatApp.description.ilike(pattern),
                )
            )
        if is_enabled is not None:
            conditions.append(ChatApp.is_enabled.is_(is_enabled))
        base_stmt = select(ChatApp).where(*conditions)
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = int((await self._session.execute(count_stmt)).scalar_one() or 0)
        stmt = (
            base_stmt.order_by(
                ChatApp.is_default.desc(),
                ChatApp.created_at.desc(),
                ChatApp.id.desc(),
            )
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_available_chat_apps(self) -> list[ChatApp]:
        stmt = (
            select(ChatApp)
            .where(ChatApp.is_enabled.is_(True), ChatApp.is_deleted.is_(False))
            .where(ChatApp.published_version_id.is_not(None))
            .order_by(ChatApp.is_default.desc(), ChatApp.created_at.desc(), ChatApp.id.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_chat_app_operation_metrics(
        self,
        *,
        keyword: str | None,
        is_enabled: bool | None,
        start_at: datetime,
        end_at: datetime,
        page: int,
        size: int,
    ) -> tuple[list[tuple[ChatApp, dict[str, Any]]], int]:
        apps, total = await self.list_chat_apps(
            keyword=keyword,
            is_enabled=is_enabled,
            page=page,
            size=size,
        )
        metrics_by_app = await self.aggregate_chat_app_operation_metrics(
            [item.id for item in apps],
            start_at=start_at,
            end_at=end_at,
        )
        return [
            (item, metrics_by_app.get(item.id, _empty_operation_metrics())) for item in apps
        ], total

    async def aggregate_chat_app_operation_metrics(
        self,
        chat_app_ids: Sequence[int],
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> dict[int, dict[str, Any]]:
        if not chat_app_ids:
            return {}
        public_share_condition = or_(
            ChatSession.source == CHAT_SESSION_SOURCE_PUBLIC_SHARE,
            ChatSession.share_id.is_not(None),
        )
        stmt = (
            select(
                ChatSession.chat_app_id.label("chat_app_id"),
                func.count(ChatMessage.id).label("total_calls"),
                func.sum(
                    case((ChatMessage.status == ChatMessageStatus.SUCCESS.value, 1), else_=0)
                ).label("success_calls"),
                func.sum(
                    case((ChatMessage.status == ChatMessageStatus.FAILED.value, 1), else_=0)
                ).label("failed_calls"),
                func.avg(ChatMessage.duration_ms).label("avg_duration_ms"),
                func.sum(case((public_share_condition, 1), else_=0)).label("public_share_calls"),
            )
            .select_from(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(
                ChatSession.chat_app_id.in_(list(chat_app_ids)),
                ChatMessage.role == ChatMessageRole.ASSISTANT.value,
                ChatMessage.is_deleted.is_(False),
                ChatMessage.created_at >= start_at,
                ChatMessage.created_at < end_at,
            )
            .group_by(ChatSession.chat_app_id)
        )
        result = await self._session.execute(stmt)
        metrics: dict[int, dict[str, Any]] = {}
        for row in result.mappings().all():
            total_calls = int(row["total_calls"] or 0)
            failed_calls = int(row["failed_calls"] or 0)
            metrics[int(row["chat_app_id"])] = {
                "total_calls": total_calls,
                "success_calls": int(row["success_calls"] or 0),
                "failed_calls": failed_calls,
                "failure_rate": failed_calls / total_calls if total_calls else 0.0,
                "avg_duration_ms": (
                    int(round(float(row["avg_duration_ms"])))
                    if row["avg_duration_ms"] is not None
                    else None
                ),
                "public_share_calls": int(row["public_share_calls"] or 0),
            }
        return metrics

    async def list_chat_app_recent_operation_errors(
        self,
        *,
        chat_app_id: int,
        start_at: datetime,
        end_at: datetime,
        limit: int,
    ) -> list[tuple[ChatMessage, ChatSession]]:
        stmt = (
            select(ChatMessage, ChatSession)
            .select_from(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(
                ChatSession.chat_app_id == chat_app_id,
                ChatMessage.role == ChatMessageRole.ASSISTANT.value,
                ChatMessage.status == ChatMessageStatus.FAILED.value,
                ChatMessage.is_deleted.is_(False),
                ChatMessage.created_at >= start_at,
                ChatMessage.created_at < end_at,
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return [(message, session) for message, session in result.all()]

    async def list_chat_app_versions(self, chat_app_id: int) -> list[ChatAppVersion]:
        stmt = (
            select(ChatAppVersion)
            .where(
                ChatAppVersion.chat_app_id == chat_app_id,
                ChatAppVersion.is_deleted.is_(False),
            )
            .order_by(ChatAppVersion.version_no.desc(), ChatAppVersion.id.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_chat_app_shares(self, chat_app_id: int) -> list[ChatAppShare]:
        stmt = (
            select(ChatAppShare)
            .where(
                ChatAppShare.chat_app_id == chat_app_id,
                ChatAppShare.is_deleted.is_(False),
            )
            .order_by(ChatAppShare.created_at.desc(), ChatAppShare.id.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_feedback_types(self, *, enabled_only: bool) -> list[ChatFeedbackType]:
        conditions: list[Any] = [ChatFeedbackType.is_deleted.is_(False)]
        if enabled_only:
            conditions.append(ChatFeedbackType.enabled.is_(True))
        stmt = (
            select(ChatFeedbackType)
            .where(*conditions)
            .order_by(ChatFeedbackType.sort_order.asc(), ChatFeedbackType.id.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_feedback_type(self, type_id: int) -> ChatFeedbackType | None:
        stmt = select(ChatFeedbackType).where(
            ChatFeedbackType.id == type_id,
            ChatFeedbackType.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_feedback_type_by_code(self, type_code: str) -> ChatFeedbackType | None:
        stmt = select(ChatFeedbackType).where(
            ChatFeedbackType.type_code == type_code,
            ChatFeedbackType.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_feedback_types_by_codes(
        self,
        type_codes: Sequence[str],
        *,
        enabled_only: bool,
    ) -> list[ChatFeedbackType]:
        if not type_codes:
            return []
        conditions: list[Any] = [
            ChatFeedbackType.type_code.in_(list(type_codes)),
            ChatFeedbackType.is_deleted.is_(False),
        ]
        if enabled_only:
            conditions.append(ChatFeedbackType.enabled.is_(True))
        stmt = select(ChatFeedbackType).where(*conditions)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create_feedback_type(
        self,
        *,
        type_code: str,
        label: str,
        description: str | None,
        enabled: bool,
        sort_order: int,
        requires_comment: bool,
        handler_key: str,
        action_schema: dict[str, Any],
        metadata: dict[str, Any],
        user_id: int,
    ) -> ChatFeedbackType:
        entity = ChatFeedbackType(
            type_code=type_code,
            label=label,
            description=description,
            enabled=enabled,
            sort_order=sort_order,
            requires_comment=requires_comment,
            handler_key=handler_key,
            action_schema_json=dict(action_schema),
            metadata_json=dict(metadata),
            created_by=user_id,
            updated_by=user_id,
        )
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def update_feedback_type(
        self,
        entity: ChatFeedbackType,
        *,
        user_id: int,
        **values: Any,
    ) -> None:
        for key, value in values.items():
            setattr(entity, key, value)
        entity.updated_by = user_id
        await self._session.flush()

    async def next_chat_app_version_no(self, chat_app_id: int) -> int:
        stmt = select(func.max(ChatAppVersion.version_no)).where(
            ChatAppVersion.chat_app_id == chat_app_id,
            ChatAppVersion.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one_or_none() or 0) + 1

    async def create_chat_app(
        self,
        *,
        name: str,
        description: str | None,
        run_mode: str,
        knowledge_ids: list[int],
        system_prompt: str | None,
        completion_model: str | None,
        temperature: float | None,
        top_k: int,
        score_threshold: float | None,
        retrieval_strategy: str,
        retrieval_config: dict[str, Any],
        is_enabled: bool,
        is_default: bool,
        user_id: int | None,
    ) -> ChatApp:
        now = datetime.now().astimezone()
        entity = ChatApp(
            name=name,
            description=description,
            run_mode=run_mode,
            knowledge_ids_json=list(knowledge_ids),
            system_prompt=system_prompt,
            completion_model=completion_model,
            temperature=temperature,
            top_k=top_k,
            score_threshold=score_threshold,
            retrieval_strategy=retrieval_strategy,
            retrieval_config_json=dict(retrieval_config),
            is_enabled=is_enabled,
            is_default=is_default,
            draft_updated_at=now,
            created_by=user_id,
            updated_by=user_id,
        )
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def create_chat_app_version(
        self,
        *,
        chat_app_id: int,
        version_no: int,
        version_name: str | None,
        publish_remark: str | None,
        config: dict[str, Any],
        is_current: bool,
        published_at: datetime,
        user_id: int | None,
    ) -> ChatAppVersion:
        entity = ChatAppVersion(
            chat_app_id=chat_app_id,
            version_no=version_no,
            version_name=version_name,
            publish_remark=publish_remark,
            config_json=dict(config),
            is_current=is_current,
            published_at=published_at,
            published_by=user_id,
            created_by=user_id,
            updated_by=user_id,
        )
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def create_chat_app_share(
        self,
        *,
        chat_app_id: int,
        version_id: int,
        version_no: int,
        share_token_hash: str,
        enabled: bool,
        expires_at: datetime | None,
        daily_limit: int | None,
        rate_limit: dict[str, Any],
        user_id: int | None,
    ) -> ChatAppShare:
        entity = ChatAppShare(
            chat_app_id=chat_app_id,
            version_id=version_id,
            version_no=version_no,
            share_token_hash=share_token_hash,
            enabled=enabled,
            expires_at=expires_at,
            daily_limit=daily_limit,
            used_count_today=0,
            used_date=None,
            last_used_at=None,
            rate_limit_json=dict(rate_limit),
            created_by=user_id,
            updated_by=user_id,
        )
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def update_chat_app_share(
        self,
        entity: ChatAppShare,
        *,
        user_id: int,
        **values: Any,
    ) -> None:
        for key, value in values.items():
            setattr(entity, key, value)
        entity.updated_by = user_id
        await self._session.flush()

    async def record_chat_app_share_usage(
        self,
        entity: ChatAppShare,
        *,
        used_date: str,
        used_at: datetime,
        user_id: int,
    ) -> None:
        if entity.used_date != used_date:
            entity.used_date = used_date
            entity.used_count_today = 0
        entity.used_count_today += 1
        entity.last_used_at = used_at
        entity.updated_by = user_id
        await self._session.flush()

    async def soft_delete_chat_app_share(
        self,
        entity: ChatAppShare,
        *,
        user_id: int,
    ) -> None:
        entity.is_deleted = True
        entity.updated_by = user_id
        await self._session.flush()

    async def clear_current_chat_app_versions(
        self, *, chat_app_id: int, user_id: int | None
    ) -> None:
        result = await self._session.execute(
            select(ChatAppVersion).where(
                ChatAppVersion.chat_app_id == chat_app_id,
                ChatAppVersion.is_current.is_(True),
                ChatAppVersion.is_deleted.is_(False),
            )
        )
        for entity in result.scalars().all():
            entity.is_current = False
            entity.updated_by = user_id
        await self._session.flush()

    async def update_chat_app_published_version(
        self,
        entity: ChatApp,
        *,
        version: ChatAppVersion,
        user_id: int | None,
    ) -> None:
        entity.published_version_id = version.id
        entity.published_version_no = version.version_no
        entity.published_at = version.published_at
        entity.draft_updated_at = version.published_at
        entity.updated_by = user_id
        await self._session.flush()

    async def clear_default_chat_apps(self, *, user_id: int | None) -> None:
        result = await self._session.execute(
            select(ChatApp).where(ChatApp.is_default.is_(True), ChatApp.is_deleted.is_(False))
        )
        for entity in result.scalars().all():
            entity.is_default = False
            entity.updated_by = user_id
        await self._session.flush()

    async def update_chat_app(self, entity: ChatApp, *, user_id: int, **values: Any) -> None:
        for key, value in values.items():
            setattr(entity, key, value)
        entity.updated_by = user_id
        await self._session.flush()

    async def set_chat_app_enabled(
        self,
        entity: ChatApp,
        *,
        is_enabled: bool,
        user_id: int,
    ) -> None:
        entity.is_enabled = is_enabled
        entity.updated_by = user_id
        await self._session.flush()

    async def soft_delete_chat_app(self, entity: ChatApp, *, user_id: int) -> None:
        entity.is_deleted = True
        entity.updated_by = user_id
        await self._session.flush()

    async def create_session(
        self,
        *,
        chat_app_id: int,
        title: str,
        user_id: int,
        project_id: int | None,
        project_name: str | None,
        last_message_at: datetime,
        share_id: int | None = None,
        visitor_id_hash: str | None = None,
        source: str = CHAT_SESSION_SOURCE_CHAT,
    ) -> ChatSession:
        entity = ChatSession(
            chat_app_id=chat_app_id,
            title=title,
            user_id=user_id,
            share_id=share_id,
            visitor_id_hash=visitor_id_hash,
            source=source,
            project_id=project_id,
            project_name=project_name,
            last_message_at=last_message_at,
            metadata_json={},
            created_by=user_id,
            updated_by=user_id,
        )
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def create_project(self, *, user_id: int, name: str) -> ChatProject:
        entity = ChatProject(
            user_id=user_id,
            name=name,
            created_by=user_id,
            updated_by=user_id,
        )
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def list_projects_for_user(self, *, user_id: int) -> list[ChatProject]:
        stmt = (
            select(ChatProject)
            .where(
                ChatProject.user_id == user_id,
                ChatProject.is_deleted.is_(False),
            )
            .order_by(ChatProject.created_at.asc(), ChatProject.id.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_project_for_user(
        self,
        *,
        project_id: int,
        user_id: int,
        for_update: bool = False,
    ) -> ChatProject | None:
        stmt = select(ChatProject).where(
            ChatProject.id == project_id,
            ChatProject.user_id == user_id,
            ChatProject.is_deleted.is_(False),
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_sessions_for_project(
        self,
        *,
        project_id: int,
        user_id: int,
        for_update: bool = False,
    ) -> list[ChatSession]:
        stmt = (
            select(ChatSession)
            .where(
                ChatSession.project_id == project_id,
                ChatSession.user_id == user_id,
                ChatSession.share_id.is_(None),
                ChatSession.is_deleted.is_(False),
            )
            .order_by(ChatSession.id.asc())
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_session_for_user(
        self,
        *,
        session_id: int,
        user_id: int,
        for_update: bool = False,
    ) -> ChatSession | None:
        stmt = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
            ChatSession.share_id.is_(None),
            ChatSession.is_deleted.is_(False),
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_sessions_for_user(
        self,
        *,
        user_id: int,
        page: int,
        size: int,
    ) -> tuple[list[ChatSession], int]:
        base_stmt = select(ChatSession).where(
            ChatSession.user_id == user_id,
            ChatSession.share_id.is_(None),
            ChatSession.is_deleted.is_(False),
        )
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = int((await self._session.execute(count_stmt)).scalar_one() or 0)
        stmt = (
            base_stmt.order_by(ChatSession.last_message_at.desc(), ChatSession.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def get_public_session(
        self,
        *,
        share_id: int,
        visitor_id_hash: str,
    ) -> ChatSession | None:
        stmt = (
            select(ChatSession)
            .where(
                ChatSession.share_id == share_id,
                ChatSession.visitor_id_hash == visitor_id_hash,
                ChatSession.source == CHAT_SESSION_SOURCE_PUBLIC_SHARE,
                ChatSession.is_deleted.is_(False),
            )
            .order_by(ChatSession.id.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_session_activity(
        self,
        entity: ChatSession,
        *,
        last_message_at: datetime,
        user_id: int,
    ) -> None:
        entity.last_message_at = last_message_at
        entity.updated_by = user_id
        await self._session.flush()

    async def update_session_metadata(
        self,
        entity: ChatSession,
        *,
        metadata: dict[str, Any],
        user_id: int,
    ) -> None:
        entity.metadata_json = dict(metadata)
        entity.updated_by = user_id
        await self._session.flush()

    async def update_session_project(
        self,
        entity: ChatSession,
        *,
        project_id: int | None,
        project_name: str | None,
        user_id: int,
    ) -> None:
        entity.project_id = project_id
        entity.project_name = project_name
        entity.updated_by = user_id
        await self._session.flush()

    async def soft_delete_session(self, entity: ChatSession, *, user_id: int) -> None:
        entity.is_deleted = True
        entity.updated_by = user_id
        await self._session.flush()

    async def soft_delete_sessions(
        self,
        entities: Sequence[ChatSession],
        *,
        user_id: int,
    ) -> None:
        for entity in entities:
            entity.is_deleted = True
            entity.updated_by = user_id
        await self._session.flush()

    async def soft_delete_project(self, entity: ChatProject, *, user_id: int) -> None:
        entity.is_deleted = True
        entity.updated_by = user_id
        await self._session.flush()

    async def list_session_file_ids(self, *, session_id: int) -> list[int]:
        """收集会话消息与文件上下文引用的文件 ID。"""
        result: list[int] = []
        seen: set[int] = set()

        message_stmt = select(ChatMessage.file_ids_json, ChatMessage.attachments_json).where(
            ChatMessage.session_id == session_id,
            ChatMessage.is_deleted.is_(False),
        )
        message_result = await self._session.execute(message_stmt)
        for file_ids_json, attachments_json in message_result.all():
            _append_json_file_ids(result, seen, file_ids_json)
            _append_attachment_file_ids(result, seen, attachments_json)

        context_stmt = select(
            ChatFileContext.source_file_id, ChatFileContext.extracted_file_id
        ).where(
            ChatFileContext.session_id == session_id,
            ChatFileContext.is_deleted.is_(False),
        )
        context_result = await self._session.execute(context_stmt)
        for source_file_id, extracted_file_id in context_result.all():
            _append_positive_int(result, seen, source_file_id)
            _append_positive_int(result, seen, extracted_file_id)

        return result

    async def create_message(
        self,
        *,
        session_id: int,
        role: str,
        content: str,
        status: str,
        user_id: int,
        run_mode: str | None = None,
        trace_id: str | None = None,
        request_id: str | None = None,
        generation_name: str | None = None,
        observability_provider: str | None = None,
        observability_env: str | None = None,
        knowledge_ids: Sequence[int] | None = None,
        file_ids: Sequence[int] | None = None,
        attachments: Sequence[dict[str, Any]] | None = None,
        evidences: Sequence[dict[str, Any]] | None = None,
        citations: Sequence[dict[str, Any]] | None = None,
        usage: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        duration_ms: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessage:
        entity = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            status=status,
            run_mode=run_mode,
            trace_id=trace_id,
            request_id=request_id,
            generation_name=generation_name,
            observability_provider=observability_provider,
            observability_env=observability_env,
            knowledge_ids_json=list(knowledge_ids or []),
            file_ids_json=list(file_ids or []),
            attachments_json=list(attachments or []),
            evidences_json=list(evidences or []),
            citations_json=list(citations or []),
            usage_json=dict(usage or {}),
            error_json=dict(error or {}),
            duration_ms=duration_ms,
            metadata_json=dict(metadata or {}),
            created_by=user_id,
            updated_by=user_id,
        )
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def update_message_file_context(
        self,
        entity: ChatMessage,
        *,
        file_ids: Sequence[int],
        attachments: Sequence[dict[str, Any]],
        user_id: int,
    ) -> None:
        entity.file_ids_json = list(file_ids)
        entity.attachments_json = list(attachments)
        entity.updated_by = user_id
        await self._session.flush()

    async def update_message_observability(
        self,
        entity: ChatMessage,
        *,
        trace_id: str | None,
        request_id: str | None,
        generation_name: str | None,
        observability_provider: str | None,
        observability_env: str | None,
        user_id: int,
    ) -> None:
        entity.trace_id = trace_id
        entity.request_id = request_id
        entity.generation_name = generation_name
        entity.observability_provider = observability_provider
        entity.observability_env = observability_env
        entity.updated_by = user_id
        await self._session.flush()

    async def list_messages_by_session(
        self,
        *,
        session_id: int,
        page: int,
        size: int,
    ) -> tuple[list[ChatMessage], int]:
        base_stmt = select(ChatMessage).where(
            ChatMessage.session_id == session_id,
            ChatMessage.is_deleted.is_(False),
        )
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = int((await self._session.execute(count_stmt)).scalar_one() or 0)
        stmt = (
            base_stmt.order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def get_message(self, message_id: int) -> ChatMessage | None:
        stmt = select(ChatMessage).where(
            ChatMessage.id == message_id,
            ChatMessage.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_previous_user_message(
        self,
        *,
        session_id: int,
        before_message: ChatMessage,
    ) -> ChatMessage | None:
        stmt = (
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == "user",
                ChatMessage.is_deleted.is_(False),
                or_(
                    ChatMessage.created_at < before_message.created_at,
                    (
                        (ChatMessage.created_at == before_message.created_at)
                        & (ChatMessage.id < before_message.id)
                    ),
                ),
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_feedback_for_user_message(
        self,
        *,
        message_id: int,
        user_id: int,
    ) -> ChatFeedback | None:
        stmt = select(ChatFeedback).where(
            ChatFeedback.message_id == message_id,
            ChatFeedback.user_id == user_id,
            ChatFeedback.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_feedbacks_for_user_messages(
        self,
        *,
        message_ids: Sequence[int],
        user_id: int,
    ) -> list[ChatFeedback]:
        if not message_ids:
            return []
        stmt = select(ChatFeedback).where(
            ChatFeedback.message_id.in_(list(message_ids)),
            ChatFeedback.user_id == user_id,
            ChatFeedback.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create_feedback(
        self,
        *,
        message_id: int,
        session_id: int,
        chat_app_id: int,
        chat_app_version_id: int | None,
        chat_app_version_no: int | None,
        user_id: int,
        rating: str,
        type_codes: Sequence[str],
        comment: str | None,
        status: str,
        handler_results: dict[str, Any],
        question_message_id: int | None,
        question_content: str | None,
        answer_content: str,
        citations: Sequence[dict[str, Any]],
        evidences: Sequence[dict[str, Any]],
        run_mode: str | None,
        trace_id: str | None,
        request_id: str | None,
        generation_name: str | None,
        observability_provider: str | None,
        observability_env: str | None,
        metadata: dict[str, Any],
    ) -> ChatFeedback:
        entity = ChatFeedback(
            message_id=message_id,
            session_id=session_id,
            chat_app_id=chat_app_id,
            chat_app_version_id=chat_app_version_id,
            chat_app_version_no=chat_app_version_no,
            user_id=user_id,
            rating=rating,
            type_codes_json=list(type_codes),
            comment=comment,
            status=status,
            admin_note=None,
            handler_results_json=dict(handler_results),
            is_eval_candidate=False,
            eval_tags_json=[],
            eval_note=None,
            reviewed_by=None,
            reviewed_at=None,
            question_message_id=question_message_id,
            question_content=question_content,
            answer_content=answer_content,
            citations_json=list(citations),
            evidences_json=list(evidences),
            run_mode=run_mode,
            trace_id=trace_id,
            request_id=request_id,
            generation_name=generation_name,
            observability_provider=observability_provider,
            observability_env=observability_env,
            metadata_json=dict(metadata),
            created_by=user_id,
            updated_by=user_id,
        )
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def update_feedback(
        self,
        entity: ChatFeedback,
        *,
        user_id: int,
        **values: Any,
    ) -> None:
        for key, value in values.items():
            setattr(entity, key, value)
        entity.updated_by = user_id
        await self._session.flush()

    async def soft_delete_feedback(self, entity: ChatFeedback, *, user_id: int) -> None:
        entity.is_deleted = True
        entity.updated_by = user_id
        await self._session.flush()

    async def list_feedbacks(
        self,
        *,
        rating: str | None,
        type_code: str | None,
        status: str | None,
        chat_app_id: int | None,
        is_eval_candidate: bool | None,
        keyword: str | None,
        page: int,
        size: int,
    ) -> tuple[list[ChatFeedback], int]:
        conditions: list[Any] = [ChatFeedback.is_deleted.is_(False)]
        if rating is not None:
            conditions.append(ChatFeedback.rating == rating)
        if type_code is not None:
            conditions.append(cast(ChatFeedback.type_codes_json, String).ilike(f'%"{type_code}"%'))
        if status is not None:
            conditions.append(ChatFeedback.status == status)
        if chat_app_id is not None:
            conditions.append(ChatFeedback.chat_app_id == chat_app_id)
        if is_eval_candidate is not None:
            conditions.append(ChatFeedback.is_eval_candidate.is_(is_eval_candidate))
        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(
                or_(
                    ChatFeedback.question_content.ilike(pattern),
                    ChatFeedback.answer_content.ilike(pattern),
                    ChatFeedback.comment.ilike(pattern),
                    ChatFeedback.admin_note.ilike(pattern),
                )
            )
        base_stmt = select(ChatFeedback).where(*conditions)
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total = int((await self._session.execute(count_stmt)).scalar_one() or 0)
        stmt = (
            base_stmt.order_by(ChatFeedback.created_at.desc(), ChatFeedback.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all()), total

    async def get_feedback(self, feedback_id: int) -> ChatFeedback | None:
        stmt = select(ChatFeedback).where(
            ChatFeedback.id == feedback_id,
            ChatFeedback.is_deleted.is_(False),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_eval_candidate_feedbacks(self) -> list[ChatFeedback]:
        stmt = (
            select(ChatFeedback)
            .where(
                ChatFeedback.is_eval_candidate.is_(True),
                ChatFeedback.is_deleted.is_(False),
            )
            .order_by(ChatFeedback.created_at.asc(), ChatFeedback.id.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_recent_success_messages(
        self,
        *,
        session_id: int,
        limit: int,
    ) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.status == ChatMessageStatus.SUCCESS.value,
                ChatMessage.is_deleted.is_(False),
            )
            .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(reversed(list(result.scalars().all())))

    async def get_active_file_context(
        self,
        *,
        session_id: int,
        user_id: int,
        source_file_id: int,
        parse_mode: str,
        now: datetime,
    ) -> ChatFileContext | None:
        stmt = (
            select(ChatFileContext)
            .where(
                ChatFileContext.session_id == session_id,
                ChatFileContext.user_id == user_id,
                ChatFileContext.source_file_id == source_file_id,
                ChatFileContext.parse_mode == parse_mode,
                ChatFileContext.is_deleted.is_(False),
                or_(ChatFileContext.expires_at.is_(None), ChatFileContext.expires_at > now),
            )
            .order_by(ChatFileContext.id.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_reusable_file_context(
        self,
        *,
        user_id: int,
        content_hash: str,
        file_size: int,
        file_extension: str,
        parse_mode: str,
        parse_status: str,
        now: datetime,
    ) -> ChatFileContext | None:
        stmt = (
            select(ChatFileContext)
            .where(
                ChatFileContext.user_id == user_id,
                ChatFileContext.content_hash == content_hash,
                ChatFileContext.source_file_size == file_size,
                ChatFileContext.source_file_extension == file_extension,
                ChatFileContext.parse_mode == parse_mode,
                ChatFileContext.parse_status == parse_status,
                ChatFileContext.is_deleted.is_(False),
                or_(ChatFileContext.expires_at.is_(None), ChatFileContext.expires_at > now),
            )
            .order_by(ChatFileContext.updated_at.desc(), ChatFileContext.id.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_file_contexts(
        self,
        *,
        session_id: int,
        user_id: int,
        file_ids: Sequence[int],
        parse_status: str,
        now: datetime,
    ) -> list[ChatFileContext]:
        if not file_ids:
            return []
        stmt = (
            select(ChatFileContext)
            .where(
                ChatFileContext.session_id == session_id,
                ChatFileContext.user_id == user_id,
                ChatFileContext.source_file_id.in_(file_ids),
                ChatFileContext.parse_status == parse_status,
                ChatFileContext.is_deleted.is_(False),
                or_(ChatFileContext.expires_at.is_(None), ChatFileContext.expires_at > now),
            )
            .order_by(ChatFileContext.created_at.asc(), ChatFileContext.id.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create_file_context(
        self,
        *,
        session_id: int,
        user_id: int,
        source_file_id: int,
        source_file_name: str,
        source_file_extension: str,
        source_file_size: int,
        content_hash: str | None,
        parse_mode: str,
        parse_status: str,
        expires_at: datetime | None,
    ) -> ChatFileContext:
        entity = ChatFileContext(
            session_id=session_id,
            user_id=user_id,
            source_file_id=source_file_id,
            source_file_name=source_file_name,
            source_file_extension=source_file_extension,
            source_file_size=source_file_size,
            content_hash=content_hash,
            parse_mode=parse_mode,
            parse_status=parse_status,
            provider_used=None,
            extracted_file_id=None,
            extracted_expires_at=expires_at,
            chunk_count=0,
            expires_at=expires_at,
            error_json={},
            created_by=user_id,
            updated_by=user_id,
        )
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def mark_file_context_success(
        self,
        entity: ChatFileContext,
        *,
        provider_used: str | None,
        extracted_file_id: int | None,
        extracted_expires_at: datetime | None,
        chunk_count: int,
        user_id: int,
    ) -> None:
        entity.parse_status = CHAT_FILE_PARSE_STATUS_SUCCESS
        entity.provider_used = provider_used
        entity.extracted_file_id = extracted_file_id
        entity.extracted_expires_at = extracted_expires_at
        entity.chunk_count = chunk_count
        entity.error_json = {}
        entity.updated_by = user_id
        await self._session.flush()

    async def mark_file_context_failed(
        self,
        entity: ChatFileContext,
        *,
        error: dict[str, Any],
        user_id: int,
    ) -> None:
        entity.parse_status = CHAT_FILE_PARSE_STATUS_FAILED
        entity.error_json = dict(error)
        entity.updated_by = user_id
        await self._session.flush()

    async def create_file_chunks(
        self,
        *,
        context_id: int,
        source_file_id: int,
        content_hash: str | None,
        chunks: Sequence[dict[str, Any]],
        user_id: int,
    ) -> list[ChatFileChunk]:
        entities = [
            ChatFileChunk(
                context_id=context_id,
                source_file_id=source_file_id,
                content_hash=content_hash,
                chunk_index=int(item["chunk_index"]),
                heading_path=item.get("heading_path"),
                content=str(item["content"]),
                char_count=int(item["char_count"]),
                metadata_json=dict(item.get("metadata_json") or {}),
                created_by=user_id,
                updated_by=user_id,
            )
            for item in chunks
        ]
        self._session.add_all(entities)
        await self._session.flush()
        return entities

    async def list_file_chunks_by_context_ids(
        self,
        context_ids: Sequence[int],
    ) -> list[ChatFileChunk]:
        if not context_ids:
            return []
        stmt = (
            select(ChatFileChunk)
            .where(
                ChatFileChunk.context_id.in_(context_ids),
                ChatFileChunk.is_deleted.is_(False),
            )
            .order_by(ChatFileChunk.context_id.asc(), ChatFileChunk.chunk_index.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


def _append_positive_int(result: list[int], seen: set[int], value: Any) -> None:
    if value is None or isinstance(value, bool):
        return
    try:
        file_id = int(value)
    except (TypeError, ValueError):
        return
    if file_id <= 0 or file_id in seen:
        return
    seen.add(file_id)
    result.append(file_id)


def _append_json_file_ids(result: list[int], seen: set[int], raw_values: Any) -> None:
    if not isinstance(raw_values, list):
        return
    for value in raw_values:
        _append_positive_int(result, seen, value)


def _append_attachment_file_ids(result: list[int], seen: set[int], raw_values: Any) -> None:
    if not isinstance(raw_values, list):
        return
    for item in raw_values:
        if not isinstance(item, dict):
            continue
        _append_positive_int(result, seen, item.get("file_id", item.get("fileId")))


def _empty_operation_metrics() -> dict[str, Any]:
    return {
        "total_calls": 0,
        "success_calls": 0,
        "failed_calls": 0,
        "failure_rate": 0.0,
        "avg_duration_ms": None,
        "public_share_calls": 0,
    }


__all__ = ["ChatRepository"]
