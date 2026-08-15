"""ChatBI 问数 SSE 边界转换。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from cogmait_shared.observability.logging import get_request_id, logger

from ...constants.chatbi.query import (
    CHATBI_SSE_COMPLETED,
    CHATBI_SSE_FAILED,
)
from ...core import deps as core_deps
from ...domain.system.chatbi.query import ChatbiQueryRunInput, ChatbiQueryStreamEvent
from ...services.system.chatbi.query.stream_event_serializer import serialize_chatbi_stream_event
from ...services.system.chatbi.query_service import ChatbiQueryServiceError

_MISSING_REQUEST_ID = "-"
_STREAM_ERROR_MESSAGE = "问数流式输出失败"


def _format_sse_event(event: str, data: dict[str, Any]) -> str:
    serialized = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return f"event: {event}\ndata: {serialized}\n\n"


async def stream_chatbi_query_events(
    service_factory: core_deps.ChatbiQueryServiceStreamFactory,
    payload: ChatbiQueryRunInput,
) -> AsyncIterator[str]:
    async with service_factory() as service:
        try:
            async for item in service.run_query_stream(payload):
                yield _format_sse_event(item.event, serialize_chatbi_stream_event(item))
        except ChatbiQueryServiceError as exc:
            yield _format_sse_event(
                CHATBI_SSE_FAILED,
                serialize_chatbi_stream_event(
                    ChatbiQueryStreamEvent(
                        event=CHATBI_SSE_FAILED,
                        request_id=payload.request_id,
                        session_id=payload.session_id,
                        error={"message": exc.message},
                    )
                ),
            )
            yield _format_sse_event(
                CHATBI_SSE_COMPLETED,
                serialize_chatbi_stream_event(
                    ChatbiQueryStreamEvent(
                        event=CHATBI_SSE_COMPLETED,
                        request_id=payload.request_id,
                        session_id=payload.session_id,
                    )
                ),
            )
        except Exception as exc:
            logger.opt(exception=exc).error(
                "ChatBI 问数流式输出失败 request_id={} session_id={} user_id={}",
                payload.request_id,
                payload.session_id,
                payload.user_id,
            )
            yield _format_sse_event(
                CHATBI_SSE_FAILED,
                serialize_chatbi_stream_event(
                    ChatbiQueryStreamEvent(
                        event=CHATBI_SSE_FAILED,
                        request_id=payload.request_id,
                        session_id=payload.session_id,
                        error={"message": _STREAM_ERROR_MESSAGE},
                    )
                ),
            )
            yield _format_sse_event(
                CHATBI_SSE_COMPLETED,
                serialize_chatbi_stream_event(
                    ChatbiQueryStreamEvent(
                        event=CHATBI_SSE_COMPLETED,
                        request_id=payload.request_id,
                        session_id=payload.session_id,
                    )
                ),
            )


def current_request_id() -> str | None:
    request_id = get_request_id()
    if not request_id or request_id == _MISSING_REQUEST_ID:
        return None
    return request_id


__all__ = ["current_request_id", "stream_chatbi_query_events"]
