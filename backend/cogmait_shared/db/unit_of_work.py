"""SQLAlchemy 会话的轻量工作单元封装。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(slots=True)
class UnitOfWork:
    """为服务层提供统一的提交/回滚接口。"""

    session: AsyncSession

    async def __aenter__(self) -> UnitOfWork:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            await self._rollback_if_active()
            return
        if self.session.in_transaction():
            await self.commit()

    async def commit(self) -> None:
        try:
            await self.session.commit()
        except BaseException:
            await self._rollback_if_active()
            raise

    async def rollback(self) -> None:
        await self._rollback_if_active()

    async def _rollback_if_active(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()


__all__ = ["UnitOfWork"]
