"""ChatBI 问数对外服务。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from ....core.config import get_settings
from ....domain.system.chat import ChatMessageRole
from ....domain.system.chatbi.query import ChatbiQueryRunInput, ChatbiQueryStreamEvent
from ....domain.system.chatbi.query_log import ChatbiQueryLogRecord
from ....observability import ObservabilityProvider
from ....repositories.system.chat import ChatRepository
from ....repositories.system.chatbi import ChatbiQueryLogRepository
from ..llm_service import LLMService
from ..rewrite import RewriteService
from .query.query_pipeline import ChatbiQueryPipeline
from .query_errors import ChatbiQueryServiceError


class ChatbiQueryService:
    """问数 SSE 与 query_log 详情。"""

    def __init__(
        self,
        *,
        unit_of_work: Any,
        redis: Any,
        llm_service: LLMService | None = None,
        rewrite_service: RewriteService | None = None,
        observability: ObservabilityProvider | None = None,
        pipeline: ChatbiQueryPipeline | None = None,
    ) -> None:
        self._uow = unit_of_work
        session = unit_of_work.session
        self._chat_repo = ChatRepository(session)
        self._query_log_repo = ChatbiQueryLogRepository(session)
        runtime = get_settings()
        self._llm = llm_service or LLMService()
        if pipeline is not None:
            self._pipeline = pipeline
        else:
            from ....observability import get_default_observability_provider

            obs = observability or get_default_observability_provider()
            rewrite = rewrite_service or RewriteService(
                llm_service=self._llm,
                observability=obs,
            )
            self._pipeline = ChatbiQueryPipeline(
                unit_of_work=unit_of_work,
                redis=redis,
                llm_service=self._llm,
                rewrite_service=rewrite,
                observability=obs,
                encryption_key=runtime.chatbi_datasource_credential_encryption_key,
            )

    async def run_query_stream(
        self,
        payload: ChatbiQueryRunInput,
    ) -> AsyncIterator[ChatbiQueryStreamEvent]:
        async for event in self._pipeline.run_stream(payload):
            yield event

    async def get_query_log_by_assistant_message(
        self,
        *,
        message_id: int,
        user_id: int,
    ) -> ChatbiQueryLogRecord:
        record = await self._query_log_repo.get_by_assistant_message_id(message_id)
        if record is None:
            raise ChatbiQueryServiceError.not_found("问数记录不存在")
        if record.created_by != user_id:
            raise ChatbiQueryServiceError.not_found("问数记录不存在")
        message = await self._chat_repo.get_message(message_id)
        if message is None or message.role != ChatMessageRole.ASSISTANT.value:
            raise ChatbiQueryServiceError.not_found("问数记录不存在")
        session = await self._chat_repo.get_session_for_user(
            session_id=message.session_id,
            user_id=user_id,
        )
        if session is None:
            raise ChatbiQueryServiceError.not_found("问数记录不存在")
        return record


__all__ = ["ChatbiQueryService", "ChatbiQueryServiceError"]
