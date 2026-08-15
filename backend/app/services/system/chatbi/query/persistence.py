"""ChatBI 问数结果写入。"""

from __future__ import annotations

from typing import Any

from .....constants.chat import (
    CHAT_MESSAGE_ROLE_ASSISTANT,
    CHAT_MESSAGE_ROLE_USER,
    CHAT_MESSAGE_STATUS_SUCCESS,
)
from .....domain.system.chatbi import ChatbiQueryLogCreateInput
from .....domain.system.chatbi.query import ChatbiQueryRunInput
from .....observability import ObservabilityProvider
from .....repositories.system.chat import ChatRepository
from .....repositories.system.chatbi import ChatbiQueryLogRepository
from ..query_errors import ChatbiQueryServiceError
from .runtime import RunMeta


def _build_chatbi_generation_name(user_message_id: int) -> str:
    return f"ai-chatbi-message-{user_message_id}"


def _build_chatbi_langfuse_session_id(session_id: int) -> str:
    return f"ai-chat-session-{session_id}"


class ChatbiQueryPersistence:
    """负责问数链路中的会话消息与 query_log 写入。"""

    def __init__(
        self,
        *,
        unit_of_work: Any,
        chat_repo: ChatRepository,
        query_log_repo: ChatbiQueryLogRepository,
        observability: ObservabilityProvider,
    ) -> None:
        self._uow = unit_of_work
        self._chat_repo = chat_repo
        self._query_log_repo = query_log_repo
        self._observability = observability

    async def ensure_user_message(
        self,
        *,
        session_id: int,
        user_id: int,
        content: str,
        request_id: str,
    ) -> int:
        session = await self._chat_repo.get_session_for_user(
            session_id=session_id,
            user_id=user_id,
        )
        if session is None:
            raise ChatbiQueryServiceError.not_found("会话不存在")
        msg = await self._chat_repo.create_message(
            session_id=session_id,
            role=CHAT_MESSAGE_ROLE_USER,
            content=content,
            status=CHAT_MESSAGE_STATUS_SUCCESS,
            user_id=user_id,
        )
        await self._uow.commit()
        user_message_id = int(msg.id)
        self._observability.update_current_trace(
            metadata={
                "session_id": str(session_id),
                "user_message_id": str(user_message_id),
                "generation_name": _build_chatbi_generation_name(user_message_id),
                "langfuse_session_id": _build_chatbi_langfuse_session_id(session_id),
                "request_id": request_id,
            }
        )
        return user_message_id

    async def persist_success(
        self,
        *,
        payload: ChatbiQueryRunInput,
        session_id: int,
        user_message_id: int | None,
        user_question: str,
        rewritten_question: str,
        datasource_id: int | None,
        intent: str | None,
        final_sql: str | None,
        result_preview: dict[str, Any] | None,
        summary: str,
        meta: RunMeta,
        log_meta: dict[str, Any] | None = None,
        status: str = CHAT_MESSAGE_STATUS_SUCCESS,
        error: dict[str, Any] | None = None,
    ) -> None:
        session = await self._chat_repo.get_session_for_user(
            session_id=session_id,
            user_id=payload.user_id,
        )
        if session is None:
            raise ChatbiQueryServiceError.not_found("会话不存在")
        assistant = await self._chat_repo.create_message(
            session_id=session_id,
            role=CHAT_MESSAGE_ROLE_ASSISTANT,
            content=summary,
            status=status,
            user_id=payload.user_id,
            request_id=meta.request_id,
            error=error,
        )
        query_log_id = await self._query_log_repo.create(
            ChatbiQueryLogCreateInput(
                assistant_message_id=int(assistant.id),
                user_message_id=user_message_id,
                request_id=meta.request_id,
                datasource_id=datasource_id,
                user_question=user_question,
                rewritten_question=rewritten_question,
                intent=intent,
                final_sql=final_sql,
                result_preview=result_preview,
                latency_ms=(log_meta or meta.to_dict()).get("latency_ms"),
                meta=log_meta if log_meta is not None else meta.to_dict(),
                user_id=payload.user_id,
            )
        )
        await self._uow.commit()
        self._observability.update_current_trace(
            metadata={
                "assistant_message_id": str(int(assistant.id)),
                "query_log_id": str(query_log_id),
            }
        )

    def trace_persist_error(self, exc: Exception) -> None:
        self._observability.update_current_trace(metadata={"persist_error": str(exc)})
