"""问题改写策略抽象接口。"""

from __future__ import annotations

from typing import Protocol

from .context import RewriteInput, RewriteOutput


class QuestionRewriteStrategy(Protocol):
    """改写策略协议。"""

    async def rewrite(self, payload: RewriteInput) -> RewriteOutput: ...


__all__ = ["QuestionRewriteStrategy"]
