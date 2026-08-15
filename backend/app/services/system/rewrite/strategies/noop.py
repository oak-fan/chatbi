"""恒等改写策略：直接返回原文。"""

from __future__ import annotations

import time

from .....observability import ObservabilityProvider
from ..context import RewriteInput, RewriteOutput, RewriteStrategyType
from ..observability import build_rewrite_span_metadata

_SPAN_NAME = "ai.rewrite.noop"


class NoopRewriteStrategy:
    """不做改写，原样返回用户问题。"""

    def __init__(self, *, observability: ObservabilityProvider) -> None:
        self._observability = observability

    async def rewrite(self, payload: RewriteInput) -> RewriteOutput:
        started = time.perf_counter()
        output = RewriteOutput(
            rewritten_question=payload.original_question,
            original_question=payload.original_question,
            is_degraded=False,
            degradation_reason=None,
            strategy_name=RewriteStrategyType.NOOP.value,
            metadata={},
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        span_metadata = build_rewrite_span_metadata(
            strategy_type=RewriteStrategyType.NOOP,
            payload=payload,
            output=output,
            latency_ms=latency_ms,
        )
        with self._observability.span(_SPAN_NAME, metadata=span_metadata):
            return output


__all__ = ["NoopRewriteStrategy"]
