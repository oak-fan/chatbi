"""问题改写策略工厂。"""

from __future__ import annotations

from ....observability import ObservabilityProvider
from ..llm_service import LLMService
from .context import RewriteStrategyType
from .interface import QuestionRewriteStrategy
from .strategies.llm import LlmRewriteStrategy
from .strategies.noop import NoopRewriteStrategy


def create_rewrite_strategy(
    strategy_type: str | RewriteStrategyType,
    *,
    llm_service: LLMService,
    observability: ObservabilityProvider,
) -> QuestionRewriteStrategy:
    """按策略类型创建改写策略实例。"""
    normalized = (
        strategy_type.value
        if isinstance(strategy_type, RewriteStrategyType)
        else str(strategy_type).strip().lower()
    )
    if not normalized:
        raise ValueError("rewrite strategy 不能为空")
    if normalized == RewriteStrategyType.LLM.value:
        return LlmRewriteStrategy(
            llm_service=llm_service,
            observability=observability,
        )
    if normalized == RewriteStrategyType.NOOP.value:
        return NoopRewriteStrategy(observability=observability)
    raise ValueError(f"改写策略 {normalized} 未注册")


__all__ = ["create_rewrite_strategy"]
