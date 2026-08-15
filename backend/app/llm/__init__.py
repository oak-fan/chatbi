"""ai_service 内部 LLM 便捷入口。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol, cast

from ..domain.system.llm import CompletionRequest, EmbeddingRequest, Message, RerankRequest

if TYPE_CHECKING:
    from ..services.system.llm_service import LLMService, LLMServiceError

__all__ = [
    "LLMService",
    "LLMServiceError",
    "get_default_llm_service",
    "acompletion",
    "aembedding",
    "arerank",
]


def __getattr__(name: str) -> Any:
    if name in {"LLMService", "LLMServiceError"}:
        from ..services.system.llm_service import LLMService, LLMServiceError

        exports = {
            "LLMService": LLMService,
            "LLMServiceError": LLMServiceError,
        }
        return exports[name]
    raise AttributeError(name)


def get_default_llm_service() -> Any:
    from ..services.system.llm_service import get_default_llm_service as _get_default_llm_service

    return _get_default_llm_service()


class LLMFacadeServiceProtocol(Protocol):
    async def acompletion(self, request: CompletionRequest) -> Any: ...

    async def aembedding(self, request: EmbeddingRequest) -> Any: ...

    async def arerank(self, request: RerankRequest) -> Any: ...


def _normalize_messages(messages: Sequence[Message | Mapping[str, Any]]) -> list[Message]:
    normalized: list[Message] = []
    for item in messages:
        if isinstance(item, Message):
            normalized.append(item)
            continue
        if not isinstance(item, Mapping):
            raise ValueError("messages 必须为 Message 或对象列表")
        normalized.append(
            Message(
                role=cast(Any, item.get("role")),
                content=item.get("content"),
            )
        )
    return normalized


async def acompletion(
    messages: Sequence[Message | Mapping[str, Any]],
    *,
    model: str | None = None,
    stream: bool = False,
    temperature: float | None = None,
    max_tokens: int | None = None,
    top_p: float | None = None,
    stop: str | list[str] | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    timeout: float | None = None,
    metadata: dict[str, Any] | None = None,
    provider_options: dict[str, Any] | None = None,
    service: LLMFacadeServiceProtocol | None = None,
) -> Any:
    request = CompletionRequest(
        model=model,
        messages=_normalize_messages(messages),
        stream=stream,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        stop=stop,
        tools=tools or [],
        tool_choice=tool_choice,
        timeout=timeout,
        metadata=metadata or {},
        provider_options=provider_options or {},
    )
    runtime_service = service or get_default_llm_service()
    return await runtime_service.acompletion(request)


async def aembedding(
    input_texts: Sequence[str],
    *,
    model: str | None = None,
    dimensions: int | None = None,
    timeout: float | None = None,
    metadata: dict[str, Any] | None = None,
    provider_options: dict[str, Any] | None = None,
    service: LLMFacadeServiceProtocol | None = None,
) -> Any:
    request = EmbeddingRequest(
        model=model,
        input_texts=list(input_texts),
        dimensions=dimensions,
        timeout=timeout,
        metadata=metadata or {},
        provider_options=provider_options or {},
    )
    runtime_service = service or get_default_llm_service()
    return await runtime_service.aembedding(request)


async def arerank(
    query: str,
    documents: Sequence[Any],
    *,
    model: str | None = None,
    top_n: int | None = None,
    return_documents: bool = True,
    timeout: float | None = None,
    metadata: dict[str, Any] | None = None,
    provider_options: dict[str, Any] | None = None,
    service: LLMFacadeServiceProtocol | None = None,
) -> Any:
    request = RerankRequest(
        model=model,
        query=query,
        documents=list(documents),
        top_n=top_n,
        return_documents=return_documents,
        timeout=timeout,
        metadata=metadata or {},
        provider_options=provider_options or {},
    )
    runtime_service = service or get_default_llm_service()
    return await runtime_service.arerank(request)
