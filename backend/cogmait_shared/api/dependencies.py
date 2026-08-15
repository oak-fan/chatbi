"""跨服务共享的 FastAPI 依赖工厂。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol, TypeVar, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cogmait_shared.db.unit_of_work import UnitOfWork

from .response import ResponseFactory


class SessionProvider(Protocol):
    """提供数据库会话上下文的协议。"""

    def get_session(self) -> AbstractAsyncContextManager[AsyncSession]: ...


DatabaseT = TypeVar("DatabaseT")
GetDbDependency = Callable[
    ..., Awaitable[AsyncIterator[AsyncSession]] | AsyncIterator[AsyncSession]
]


def get_database_from_app_state(
    request: Request,
    *,
    expected_type: type[DatabaseT] | None = None,
    state_key: str = "database",
    missing_message: str = "数据库未在 app.state 上初始化",
) -> DatabaseT:
    """从 app.state 读取数据库实例。"""

    database = getattr(request.app.state, state_key, None)
    if expected_type is not None and not isinstance(database, expected_type):
        raise RuntimeError(missing_message)
    if expected_type is None and database is None:
        raise RuntimeError(missing_message)
    return cast(DatabaseT, database)


def build_database_dependency(
    *,
    expected_type: type[DatabaseT] | None = None,
    state_key: str = "database",
    missing_message: str = "数据库未在 app.state 上初始化",
) -> Callable[[Request], DatabaseT]:
    """构建读取 app.state 数据库实例的依赖。"""

    def dependency(request: Request) -> DatabaseT:
        return get_database_from_app_state(
            request,
            expected_type=expected_type,
            state_key=state_key,
            missing_message=missing_message,
        )

    return dependency


def build_db_session_dependency(
    get_database_dependency: Callable[..., SessionProvider],
) -> Callable[..., AsyncIterator[AsyncSession]]:
    """构建数据库会话依赖。"""

    async def dependency(
        database: SessionProvider = Depends(get_database_dependency),
    ) -> AsyncIterator[AsyncSession]:
        async with database.get_session() as session:
            yield session

    return dependency


def build_unit_of_work_dependency(
    get_db_dependency: GetDbDependency,
) -> Callable[..., UnitOfWork]:
    """构建工作单元依赖。"""

    def dependency(db: AsyncSession = Depends(get_db_dependency)) -> UnitOfWork:
        return UnitOfWork(db)

    return dependency


def get_response_factory() -> ResponseFactory:
    """统一响应封装工厂，默认注入 requestId 并返回 dict。"""
    return ResponseFactory()


__all__ = [
    "SessionProvider",
    "get_database_from_app_state",
    "build_database_dependency",
    "build_db_session_dependency",
    "build_unit_of_work_dependency",
    "get_response_factory",
]
