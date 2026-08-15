"""ai_service 数据库入口，核心实现已收敛到 shared。"""

from cogmait_shared.db import Database, get_default_database as _get_default_database

from .config import settings


def get_default_database() -> Database:
    """为 Worker/脚本等非请求场景提供默认数据库实例。"""
    return _get_default_database(
        database_url=settings.database_url,
        sql_echo=settings.sql_echo,
    )


get_default_database.cache_clear = _get_default_database.cache_clear  # type: ignore[attr-defined]


__all__ = ["Database", "get_default_database"]
