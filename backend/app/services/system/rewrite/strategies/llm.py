"""LLM 改写策略：调用大模型改写问题，失败时内部降级。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, cast

from .....domain.system.llm import CompletionRequest, CompletionResponse, Message, UsageInfo
from .....observability import ObservabilityProvider
from ...llm_service import LLMService, LLMServiceError
from ..context import RewriteInput, RewriteOutput, RewriteStrategyType
from ..observability import build_rewrite_span_metadata

_SPAN_NAME = "ai.rewrite.llm"
_DEGRADATION_REASON_MAX_LEN = 200

_REWRITE_SYSTEM = (
    "你是问题改写助手。你要结合对话历史、术语表，以及用户的当前问题，"
    "还原用户的真实意图。\n"
    "要求：\n"
    "- 只输出一行改写后的问题文本；\n"
    "- 不要输出 Markdown、JSON、解释或前后缀；\n"
    "- 保留用户核心意图，不臆造未提及的事实、指标或实体。"
)


@dataclass(slots=True)
class _LlmRewriteSuccess:
    rewritten_question: str
    model_name: str | None
    prompt_tokens: int | None
    completion_tokens: int | None


class LlmRewriteStrategy:
    """调用大模型进行语义改写，失败时降级为原文。"""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        observability: ObservabilityProvider,
    ) -> None:
        self._llm = llm_service
        self._observability = observability

    async def rewrite(self, payload: RewriteInput) -> RewriteOutput:
        started = time.perf_counter()
        span_metadata: dict[str, Any] = {}
        output: RewriteOutput

        with self._observability.span(_SPAN_NAME, metadata=span_metadata):
            try:
                success = await self._rewrite_with_completion(payload)
                output = RewriteOutput(
                    rewritten_question=success.rewritten_question,
                    original_question=payload.original_question,
                    is_degraded=False,
                    degradation_reason=None,
                    strategy_name=RewriteStrategyType.LLM.value,
                    metadata={
                        "model_name": success.model_name,
                        "prompt_tokens": success.prompt_tokens,
                        "completion_tokens": success.completion_tokens,
                    },
                )
                model_name = success.model_name
                prompt_tokens = success.prompt_tokens
                completion_tokens = success.completion_tokens
            except Exception as exc:
                output = self._build_degraded_output(payload, exc)
                model_name = None
                prompt_tokens = None
                completion_tokens = None

            latency_ms = int((time.perf_counter() - started) * 1000)
            span_metadata.update(
                build_rewrite_span_metadata(
                    strategy_type=RewriteStrategyType.LLM,
                    payload=payload,
                    output=output,
                    latency_ms=latency_ms,
                    model_name=model_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            )

        return output

    async def _rewrite_with_completion(self, payload: RewriteInput) -> _LlmRewriteSuccess:
        metadata: dict[str, Any] = {}
        if payload.request_id:
            metadata["request_id"] = payload.request_id
        if payload.user_id:
            metadata["user_id"] = payload.user_id

        request = CompletionRequest(
            messages=[
                Message(role="system", content=_REWRITE_SYSTEM),
                Message(role="user", content=_build_user_content(payload)),
            ],
            temperature=0.0,
            metadata=metadata,
        )
        try:
            response = await self._llm.acompletion(request)
        except LLMServiceError as exc:
            raise ValueError(exc.message) from exc

        if not isinstance(response, CompletionResponse):
            raise ValueError("模型返回格式无效")
        if not response.choices:
            raise ValueError("模型返回为空")
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("模型返回空内容")

        rewritten = content.strip()
        usage = response.usage
        return _LlmRewriteSuccess(
            rewritten_question=rewritten,
            model_name=response.model,
            prompt_tokens=_usage_tokens(usage, "prompt_tokens"),
            completion_tokens=_usage_tokens(usage, "completion_tokens"),
        )

    def _build_degraded_output(self, payload: RewriteInput, exc: Exception) -> RewriteOutput:
        return RewriteOutput(
            rewritten_question=payload.original_question,
            original_question=payload.original_question,
            is_degraded=True,
            degradation_reason=_truncate_reason(exc),
            strategy_name=RewriteStrategyType.LLM.value,
            metadata={},
        )


def _build_user_content(payload: RewriteInput) -> str:
    sections = [f"当前问题：{payload.original_question}"]
    if payload.recent_messages:
        history_lines = [
            f"{message.role}: {message.content}" for message in payload.recent_messages
        ]
        sections.append("最近对话：\n" + "\n".join(history_lines))
    if payload.glossary:
        sections.append("术语表：\n" + json.dumps(payload.glossary, ensure_ascii=False))
    return "\n\n".join(sections)


def _truncate_reason(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    if len(message) <= _DEGRADATION_REASON_MAX_LEN:
        return message
    return message[: _DEGRADATION_REASON_MAX_LEN - 3] + "..."


def _usage_tokens(usage: UsageInfo | None, field: str) -> int | None:
    if usage is None:
        return None
    value = getattr(usage, field, None)
    return cast(int | None, value)


__all__ = ["LlmRewriteStrategy"]
