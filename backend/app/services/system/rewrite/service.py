"""问题改写对外门面。"""

from __future__ import annotations

from ....observability import ObservabilityProvider
from ..llm_service import LLMService
from .context import RewriteInput, RewriteOutput, RewriteStrategyType
from .factory import create_rewrite_strategy


class RewriteService:
    """供 Chat / ChatBI 等模块调用的改写门面。"""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        observability: ObservabilityProvider,
    ) -> None:
        self._llm_service = llm_service
        self._observability = observability

    async def rewrite(
        self,
        payload: RewriteInput,
        *,
        strategy: str | RewriteStrategyType,
    ) -> RewriteOutput:
        """按指定策略执行问题改写。"""
        impl = create_rewrite_strategy(
            strategy,
            llm_service=self._llm_service,
            observability=self._observability,
        )
        return await impl.rewrite(payload)


__all__ = ["RewriteService"]
