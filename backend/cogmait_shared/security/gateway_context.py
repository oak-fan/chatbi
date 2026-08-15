"""Gateway 与下游服务之间的安全上下文头契约。"""

from __future__ import annotations

import json

from ..observability.logging import logger
from .session import SessionContext

USER_ID_HEADER = "x-user-id"
USERNAME_HEADER = "x-username"
ACCOUNT_TYPE_HEADER = "x-account-type"
SESSION_ID_HEADER = "x-session-id"
CLIENT_META_HEADER = "x-client-meta"
GATEWAY_TOKEN_HEADER = "x-gateway-token"  # nosec B105

DEFAULT_MAX_CLIENT_META_HEADER_LENGTH = 2048

GATEWAY_CONTEXT_HEADERS = frozenset(
    {
        USER_ID_HEADER,
        USERNAME_HEADER,
        ACCOUNT_TYPE_HEADER,
        SESSION_ID_HEADER,
        CLIENT_META_HEADER,
        GATEWAY_TOKEN_HEADER,
    }
)

HeaderPairs = list[tuple[str, str]]


def build_gateway_context_headers(
    session: SessionContext,
    *,
    max_client_meta_header_length: int = DEFAULT_MAX_CLIENT_META_HEADER_LENGTH,
) -> HeaderPairs:
    """将会话上下文序列化为网关透传头。"""
    pairs: HeaderPairs = [
        (USER_ID_HEADER, str(session.user_id)),
        (USERNAME_HEADER, session.username),
        (ACCOUNT_TYPE_HEADER, str(session.account_type)),
        (SESSION_ID_HEADER, session.session_id),
    ]
    if session.client_meta:
        client_meta = json.dumps(
            session.client_meta,
            ensure_ascii=True,
            separators=(",", ":"),
        )
        if len(client_meta) > max_client_meta_header_length:
            logger.warning(
                "x-client-meta 超过长度限制，已跳过注入：session_id={} size={}",
                session.session_id,
                len(client_meta),
            )
        else:
            pairs.append((CLIENT_META_HEADER, client_meta))
    return pairs


__all__ = [
    "ACCOUNT_TYPE_HEADER",
    "CLIENT_META_HEADER",
    "DEFAULT_MAX_CLIENT_META_HEADER_LENGTH",
    "GATEWAY_CONTEXT_HEADERS",
    "GATEWAY_TOKEN_HEADER",
    "HeaderPairs",
    "SESSION_ID_HEADER",
    "USER_ID_HEADER",
    "USERNAME_HEADER",
    "build_gateway_context_headers",
]
