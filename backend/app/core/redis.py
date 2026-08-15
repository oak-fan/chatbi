"""Redis 客户端封装。"""

from functools import lru_cache

from redis.asyncio import ConnectionPool, Redis

from .config import settings


@lru_cache
def _get_pool() -> ConnectionPool:
    """创建并缓存 Redis 连接池。"""

    return ConnectionPool.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )


def get_redis_client() -> Redis:
    """获取 Redis 客户端实例。"""

    return Redis(connection_pool=_get_pool())
