"""跨服务共享的数据库连接与会话封装。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """封装数据库引擎与会话工厂，统一管理生命周期。"""

    def __init__(self, *, database_url: str, sql_echo: bool) -> None:
        self._database_url = database_url
        self._sql_echo = sql_echo
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine | None:
        return self._engine

    def initialize(self) -> None:
        if self._session_factory is not None:
            return
        self._engine = create_async_engine(
            self._database_url,
            echo=self._sql_echo,
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
            autoflush=False,
            class_=AsyncSession,
        )

    def _get_session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            self.initialize()
        if self._session_factory is None:
            raise RuntimeError("数据库会话工厂未初始化")
        return self._session_factory

    def session(self) -> AsyncSession:
        return self._get_session_factory()()

    @asynccontextmanager
    async def get_session(self) -> AsyncIterator[AsyncSession]:
        async with self.session() as session:
            yield session

    async def dispose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
        self._engine = None
        self._session_factory = None


@lru_cache
def get_default_database(*, database_url: str, sql_echo: bool) -> Database:
    """为 Worker/脚本等非请求场景提供默认数据库实例。"""
    return Database(database_url=database_url, sql_echo=sql_echo)


__all__ = ["Database", "get_default_database"]
