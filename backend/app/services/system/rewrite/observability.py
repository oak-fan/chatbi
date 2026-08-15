"""问题改写 Span 元数据构建。"""

from __future__ import annotations

from typing import Any

from .context import RewriteInput, RewriteOutput, RewriteStrategyType


def build_rewrite_span_metadata(
    *,
    strategy_type: RewriteStrategyType | str,
    payload: RewriteInput,
    output: RewriteOutput,
    latency_ms: int,
    model_name: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> dict[str, Any]:
    """构建 ai.rewrite.* Span 统一元数据。"""
    strategy_value = (
        strategy_type.value
        if isinstance(strategy_type, RewriteStrategyType)
        else str(strategy_type).strip()
    )
    metadata: dict[str, Any] = {
        "strategy_type": strategy_value,
        "is_degraded": output.is_degraded,
        "original_length": len(payload.original_question),
        "rewritten_length": len(output.rewritten_question),
        "has_history": payload.has_history,
        "has_glossary": payload.has_glossary,
        "latency_ms": latency_ms,
    }
    if strategy_value == RewriteStrategyType.LLM.value:
        metadata["model_name"] = model_name
        metadata["prompt_tokens"] = prompt_tokens
        metadata["completion_tokens"] = completion_tokens
    return metadata


__all__ = ["build_rewrite_span_metadata"]
