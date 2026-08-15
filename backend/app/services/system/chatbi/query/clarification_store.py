"""ChatBI 澄清续传 Redis 快照。"""

from __future__ import annotations

import json
import secrets
from typing import Any

from redis.asyncio import Redis

from .....constants.chatbi.query import (
    CHATBI_CLARIFICATION_REDIS_PREFIX,
    CHATBI_CLARIFICATION_TTL_SECONDS,
)
from .....core.config import Settings, settings


class ChatbiClarificationStore:
    """存储澄清续传快照，键受 REDIS_KEY_PREFIX 影响。"""

    def __init__(self, *, redis: Redis, config: Settings = settings) -> None:
        self._redis = redis
        prefix = (config.redis_key_prefix or "").strip()
        base = CHATBI_CLARIFICATION_REDIS_PREFIX
        self._key_prefix = f"{prefix}:{base}" if prefix else base

    def _key(self, token: str) -> str:
        return f"{self._key_prefix}:{token}"

    @staticmethod
    def generate_token() -> str:
        return secrets.token_urlsafe(32)

    async def save(
        self,
        *,
        token: str,
        payload: dict[str, Any],
        ttl_seconds: int = CHATBI_CLARIFICATION_TTL_SECONDS,
    ) -> None:
        await self._redis.set(
            self._key(token),
            json.dumps(payload, ensure_ascii=False),
            ex=ttl_seconds,
        )

    async def load(self, token: str) -> dict[str, Any] | None:
        raw = await self._redis.get(self._key(token))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    async def delete(self, token: str) -> None:
        await self._redis.delete(self._key(token))


__all__ = ["ChatbiClarificationStore"]
