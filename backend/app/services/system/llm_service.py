"""LiteLLM service facade for ai_service."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from functools import lru_cache
from typing import Any, Protocol

from cogmait_shared.core.api_codes import ErrorCode, HttpStatus
from cogmait_shared.clients.contracts.main_api import ConfigClient, ConfigClientError
from cogmait_shared.observability.logging import logger

from ...constants.llm import (
    AI_DEFAULT_COMPLETION_MODEL_CONFIG_KEY,
    AI_DEFAULT_EMBEDDING_MODEL_CONFIG_KEY,
    AI_DEFAULT_RERANK_MODEL_CONFIG_KEY,
)
from ...core.config import Settings, settings
from ...domain.system.llm import (
    CompletionChoice,
    CompletionChunk,
    CompletionModelOption,
    CompletionRequest,
    CompletionResponse,
    EmbeddingModelOption,
    EmbeddingRequest,
    EmbeddingResponse,
    Message,
    RerankItem,
    RerankRequest,
    RerankResponse,
    UsageInfo,
)
from ...llm.runtime import LiteLLMRuntime, LiteLLMRuntimeError

__all__ = ["LLMService", "LLMServiceError", "get_default_llm_service"]

_COMPLETION_RESERVED_FIELDS = {
    "model",
    "messages",
    "stream",
    "temperature",
    "max_tokens",
    "top_p",
    "stop",
    "tools",
    "tool_choice",
    "timeout",
}
_EMBEDDING_RESERVED_FIELDS = {"model", "input", "input_texts", "timeout", "dimensions"}
_RERANK_RESERVED_FIELDS = {"model", "query", "documents", "top_n", "return_documents", "timeout"}


class LLMRuntimeProtocol(Protocol):
    async def acompletion(self, **kwargs: Any) -> Any: ...

    async def aembedding(self, **kwargs: Any) -> Any: ...

    async def arerank(self, **kwargs: Any) -> Any: ...

    async def list_embedding_models(self) -> list[str]: ...

    async def list_completion_models(self) -> list[str]: ...


class ConfigValueClientProtocol(Protocol):
    async def get_value(self, config_key: str, *, request_id: str | None = None) -> str | None: ...


class LLMServiceError(Exception):
    """统一的 LLM 服务异常。"""

    def __init__(self, message: str, *, status_code: int, code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code

    @classmethod
    def bad_request(cls, message: str) -> LLMServiceError:
        return cls(message, status_code=HttpStatus.BAD_REQUEST, code=ErrorCode.PARAMS_INVALID)

    @classmethod
    def bad_gateway(cls, message: str) -> LLMServiceError:
        return cls(message, status_code=HttpStatus.BAD_GATEWAY, code=ErrorCode.SYSTEM_ERROR)

    @classmethod
    def system_error(cls, message: str) -> LLMServiceError:
        return cls(message, status_code=HttpStatus.INTERNAL_ERROR, code=ErrorCode.SYSTEM_ERROR)


class LLMService:
    """统一的模型能力服务入口。"""

    def __init__(
        self,
        *,
        runtime: LLMRuntimeProtocol | None = None,
        config: Settings = settings,
        config_client: ConfigValueClientProtocol | None = None,
    ) -> None:
        self._config = config
        self._runtime = runtime or LiteLLMRuntime(config=config)
        self._config_client = config_client

    async def acompletion(
        self,
        req: CompletionRequest,
    ) -> CompletionResponse | AsyncIterator[CompletionChunk]:
        self._validate_completion_request(req)
        model = await self.resolve_completion_model(req.model)
        payload = self._build_completion_payload(req, model=model)
        try:
            raw_response = await self._runtime.acompletion(**payload)
        except LiteLLMRuntimeError as exc:
            raise LLMServiceError.system_error(str(exc)) from exc
        except Exception as exc:
            logger.opt(exception=exc).error("LiteLLM completion 调用失败")
            raise LLMServiceError.bad_gateway(f"LiteLLM completion 调用失败：{exc}") from exc
        if req.stream:
            return self._completion_stream(raw_response)
        return self._to_completion_response(raw_response, fallback_model=model)

    async def aembedding(self, req: EmbeddingRequest) -> EmbeddingResponse:
        self._validate_embedding_request(req)
        model = await self.resolve_embedding_model(req.model)
        payload = self._build_embedding_payload(req, model=model)
        try:
            raw_response = await self._runtime.aembedding(**payload)
        except LiteLLMRuntimeError as exc:
            raise LLMServiceError.system_error(str(exc)) from exc
        except Exception as exc:
            logger.opt(exception=exc).error("LiteLLM embedding 调用失败")
            raise LLMServiceError.bad_gateway(f"LiteLLM embedding 调用失败：{exc}") from exc
        return self._to_embedding_response(raw_response, fallback_model=model)

    async def arerank(self, req: RerankRequest) -> RerankResponse:
        self._validate_rerank_request(req)
        model = await self.resolve_rerank_model(req.model)
        payload = self._build_rerank_payload(req, model=model)
        try:
            raw_response = await self._runtime.arerank(**payload)
        except LiteLLMRuntimeError as exc:
            raise LLMServiceError.system_error(str(exc)) from exc
        except Exception as exc:
            logger.opt(exception=exc).error("LiteLLM rerank 调用失败")
            raise LLMServiceError.bad_gateway(f"LiteLLM rerank 调用失败：{exc}") from exc
        return self._to_rerank_response(raw_response, fallback_model=model)

    async def list_embedding_models(self) -> list[EmbeddingModelOption]:
        """获取 LiteLLM 暴露的 embedding 模型列表。"""

        try:
            raw_models = await self._runtime.list_embedding_models()
        except LiteLLMRuntimeError as exc:
            raise LLMServiceError.system_error(str(exc)) from exc
        except Exception as exc:
            logger.opt(exception=exc).error("LiteLLM embedding 模型列表获取失败")
            raise LLMServiceError.bad_gateway(f"LiteLLM embedding 模型列表获取失败：{exc}") from exc

        return [EmbeddingModelOption(label=model, value=model) for model in raw_models]

    async def list_completion_models(self) -> list[CompletionModelOption]:
        """获取 LiteLLM 暴露的 completion/chat 模型列表。"""

        try:
            raw_models = await self._runtime.list_completion_models()
        except LiteLLMRuntimeError as exc:
            raise LLMServiceError.system_error(str(exc)) from exc
        except Exception as exc:
            logger.opt(exception=exc).error("LiteLLM completion 模型列表获取失败")
            raise LLMServiceError.bad_gateway(
                f"LiteLLM completion 模型列表获取失败：{exc}"
            ) from exc

        return [CompletionModelOption(label=model, value=model) for model in raw_models]

    async def resolve_completion_model(self, model: str | None = None) -> str:
        """解析 completion 默认模型。"""

        return await self._resolve_model(
            model,
            config_key=AI_DEFAULT_COMPLETION_MODEL_CONFIG_KEY,
            model_label="completion",
        )

    async def resolve_embedding_model(self, model: str | None = None) -> str:
        """解析 embedding 默认模型。"""

        return await self._resolve_model(
            model,
            config_key=AI_DEFAULT_EMBEDDING_MODEL_CONFIG_KEY,
            model_label="embedding",
        )

    async def resolve_rerank_model(self, model: str | None = None) -> str:
        """解析 rerank 默认模型。"""

        return await self._resolve_model(
            model,
            config_key=AI_DEFAULT_RERANK_MODEL_CONFIG_KEY,
            model_label="rerank",
        )

    def _build_completion_payload(self, req: CompletionRequest, *, model: str) -> dict[str, Any]:
        payload = self._filter_provider_options(req.provider_options, _COMPLETION_RESERVED_FIELDS)
        payload.update(
            {
                "model": model,
                "messages": [self._message_to_payload(message) for message in req.messages],
                "stream": req.stream,
            }
        )
        if req.temperature is not None:
            payload["temperature"] = req.temperature
        if req.max_tokens is not None:
            payload["max_tokens"] = req.max_tokens
        if req.top_p is not None:
            payload["top_p"] = req.top_p
        if req.stop is not None:
            payload["stop"] = req.stop
        if req.tools:
            payload["tools"] = req.tools
        if req.tool_choice is not None:
            payload["tool_choice"] = req.tool_choice
        if req.timeout is not None:
            payload["timeout"] = req.timeout
        if req.metadata:
            payload["metadata"] = req.metadata
        return payload

    def _build_embedding_payload(self, req: EmbeddingRequest, *, model: str) -> dict[str, Any]:
        payload = self._filter_provider_options(req.provider_options, _EMBEDDING_RESERVED_FIELDS)
        payload.update(
            {
                "model": model,
                "input": req.input_texts,
            }
        )
        if req.dimensions is not None:
            payload["dimensions"] = req.dimensions
        if req.timeout is not None:
            payload["timeout"] = req.timeout
        if req.metadata:
            payload["metadata"] = req.metadata
        return payload

    def _build_rerank_payload(self, req: RerankRequest, *, model: str) -> dict[str, Any]:
        payload = self._filter_provider_options(req.provider_options, _RERANK_RESERVED_FIELDS)
        payload.update(
            {
                "model": model,
                "query": req.query,
                "documents": req.documents,
                "return_documents": req.return_documents,
            }
        )
        if req.top_n is not None:
            payload["top_n"] = req.top_n
        if req.timeout is not None:
            payload["timeout"] = req.timeout
        if req.metadata:
            payload["metadata"] = req.metadata
        return payload

    def _validate_completion_request(self, req: CompletionRequest) -> None:
        if not req.messages:
            raise LLMServiceError.bad_request("messages 不能为空")
        self._validate_temperature(req.temperature)
        self._validate_top_p(req.top_p)
        self._validate_positive_int(req.max_tokens, field_name="max_tokens")
        self._validate_timeout(req.timeout)

    def _validate_embedding_request(self, req: EmbeddingRequest) -> None:
        if not req.input_texts:
            raise LLMServiceError.bad_request("input_texts 不能为空")
        self._validate_positive_int(req.dimensions, field_name="dimensions")
        self._validate_timeout(req.timeout)

    def _validate_rerank_request(self, req: RerankRequest) -> None:
        if not req.query:
            raise LLMServiceError.bad_request("query 不能为空")
        if not req.documents:
            raise LLMServiceError.bad_request("documents 不能为空")
        self._validate_positive_int(req.top_n, field_name="top_n")
        self._validate_timeout(req.timeout)

    @staticmethod
    def _validate_temperature(temperature: float | None) -> None:
        if temperature is None:
            return
        if temperature < 0 or temperature > 2:
            raise LLMServiceError.bad_request("temperature 必须在 0 到 2 之间")

    @staticmethod
    def _validate_top_p(top_p: float | None) -> None:
        if top_p is None:
            return
        if top_p <= 0 or top_p > 1:
            raise LLMServiceError.bad_request("top_p 必须在 0 到 1 之间")

    @staticmethod
    def _validate_positive_int(value: int | None, *, field_name: str) -> None:
        if value is None:
            return
        if value <= 0:
            raise LLMServiceError.bad_request(f"{field_name} 必须大于 0")

    @staticmethod
    def _validate_timeout(timeout: float | None) -> None:
        if timeout is None:
            return
        if timeout <= 0:
            raise LLMServiceError.bad_request("timeout 必须大于 0")

    async def _resolve_model(self, model: str | None, *, config_key: str, model_label: str) -> str:
        candidate = (model or "").strip()
        if candidate:
            return candidate
        fallback = (await self._get_system_config_value(config_key) or "").strip()
        if fallback:
            return fallback
        raise LLMServiceError.system_error(
            f"未配置默认 {model_label} 模型，请在系统参数 {config_key} 中配置"
        )

    async def _get_system_config_value(self, config_key: str) -> str | None:
        env_fallback = {
            AI_DEFAULT_COMPLETION_MODEL_CONFIG_KEY: settings.default_completion_model,
            AI_DEFAULT_EMBEDDING_MODEL_CONFIG_KEY: settings.default_embedding_model,
            AI_DEFAULT_RERANK_MODEL_CONFIG_KEY: settings.default_rerank_model,
        }.get(config_key)
        if env_fallback:
            return env_fallback
        try:
            if self._config_client is not None:
                return await self._config_client.get_value(config_key)
            async with ConfigClient() as client:
                return await client.get_value(config_key)
        except (ConfigClientError, ValueError) as exc:
            raise LLMServiceError.system_error(f"读取系统参数 {config_key} 失败：{exc}") from exc

    async def _completion_stream(self, raw_stream: Any) -> AsyncIterator[CompletionChunk]:
        if not hasattr(raw_stream, "__aiter__"):
            raise LLMServiceError.bad_gateway("LiteLLM completion 流式返回非法")
        async for chunk in raw_stream:
            yield self._to_completion_chunk(chunk)

    def _to_completion_response(
        self,
        raw_response: Any,
        *,
        fallback_model: str,
    ) -> CompletionResponse:
        raw_choices = self._require_sequence(
            raw_response,
            "choices",
            "LiteLLM completion 返回缺少 choices",
        )
        choices: list[CompletionChoice] = []
        for index, choice in enumerate(raw_choices):
            raw_message = self._get_value(choice, "message")
            if raw_message is None:
                raise LLMServiceError.bad_gateway("LiteLLM completion 返回缺少 message")
            choices.append(
                CompletionChoice(
                    index=self._to_int(self._get_value(choice, "index"), default=index),
                    message=self._to_message(raw_message),
                    finish_reason=self._to_optional_str(self._get_value(choice, "finish_reason")),
                )
            )
        usage = self._to_usage_info(self._get_value(raw_response, "usage"))
        model = self._to_optional_str(self._get_value(raw_response, "model")) or fallback_model
        return CompletionResponse(model=model, choices=choices, usage=usage)

    def _to_completion_chunk(self, raw_chunk: Any) -> CompletionChunk:
        raw_choices = self._require_sequence(
            raw_chunk,
            "choices",
            "LiteLLM completion 流式返回缺少 choices",
        )
        raw_choice = self._first_item(raw_choices)
        raw_delta = self._get_value(raw_choice, "delta")
        if raw_delta is None:
            raw_delta = self._get_value(raw_choice, "message")
        if raw_delta is None:
            raise LLMServiceError.bad_gateway("LiteLLM completion 流式返回缺少 delta")
        finish_reason = self._to_optional_str(self._get_value(raw_choice, "finish_reason"))
        return CompletionChunk(
            delta=self._normalize_delta(raw_delta),
            finish_reason=finish_reason,
        )

    def _to_embedding_response(
        self,
        raw_response: Any,
        *,
        fallback_model: str,
    ) -> EmbeddingResponse:
        raw_items = self._require_sequence(raw_response, "data", "LiteLLM embedding 返回缺少 data")
        if len(raw_items) == 0:
            raise LLMServiceError.bad_gateway("LiteLLM embedding 返回 data 为空")
        embeddings: list[list[float]] = []
        for item in raw_items:
            raw_embedding = self._require_sequence(
                item,
                "embedding",
                "LiteLLM embedding 返回缺少 embedding",
            )
            embeddings.append([float(value) for value in raw_embedding])
        dimensions = len(embeddings[0]) if embeddings else 0
        usage = self._to_usage_info(self._get_value(raw_response, "usage"))
        model = self._to_optional_str(self._get_value(raw_response, "model")) or fallback_model
        return EmbeddingResponse(
            model=model,
            embeddings=embeddings,
            dimensions=dimensions,
            usage=usage,
        )

    def _to_rerank_response(
        self,
        raw_response: Any,
        *,
        fallback_model: str,
    ) -> RerankResponse:
        raw_items = self._require_sequence(
            raw_response,
            "results",
            "LiteLLM rerank 返回缺少 results",
        )
        results = [
            RerankItem(
                index=self._to_int(self._get_value(item, "index"), default=index),
                document=self._get_value(item, "document"),
                score=self._to_optional_float(
                    self._get_value(item, "relevance_score", self._get_value(item, "score"))
                ),
            )
            for index, item in enumerate(raw_items)
        ]
        model = self._to_optional_str(self._get_value(raw_response, "model")) or fallback_model
        return RerankResponse(model=model, results=results)

    @staticmethod
    def _filter_provider_options(
        provider_options: Mapping[str, Any],
        reserved_fields: set[str],
    ) -> dict[str, Any]:
        return {
            key: value
            for key, value in provider_options.items()
            if key not in reserved_fields and value is not None
        }

    @staticmethod
    def _message_to_payload(message: Message) -> dict[str, Any]:
        return {"role": message.role, "content": message.content}

    @staticmethod
    def _to_usage_info(raw_usage: Any) -> UsageInfo | None:
        if raw_usage is None:
            return None
        return UsageInfo(
            prompt_tokens=LLMService._to_optional_int(
                LLMService._get_value(raw_usage, "prompt_tokens")
            ),
            completion_tokens=LLMService._to_optional_int(
                LLMService._get_value(raw_usage, "completion_tokens")
            ),
            total_tokens=LLMService._to_optional_int(
                LLMService._get_value(raw_usage, "total_tokens")
            ),
        )

    @staticmethod
    def _to_message(raw_message: Any) -> Message:
        if isinstance(raw_message, str):
            return Message(role="assistant", content=raw_message)
        role = (
            LLMService._to_optional_str(LLMService._get_value(raw_message, "role")) or "assistant"
        )
        content = LLMService._get_value(raw_message, "content")
        if content is None:
            content = (
                LLMService._get_value(raw_message, "reasoning_content")
                or ""
            )
        return Message(role=role, content=content)

    @staticmethod
    def _normalize_delta(raw_delta: Any) -> str | dict[str, Any]:
        if raw_delta is None:
            return ""
        if isinstance(raw_delta, str):
            return raw_delta
        if isinstance(raw_delta, Mapping):
            compacted = {key: value for key, value in raw_delta.items() if value is not None}
            if set(compacted) == {"content"} and isinstance(compacted["content"], str):
                return compacted["content"]
            return dict(compacted)
        model_dump = getattr(raw_delta, "model_dump", None)
        if callable(model_dump):
            return LLMService._normalize_delta(model_dump(exclude_none=True))
        content = LLMService._get_value(raw_delta, "content")
        if isinstance(content, str):
            return content
        return {}

    @staticmethod
    def _require_sequence(obj: Any, key: str, message: str) -> Sequence[Any]:
        value = LLMService._get_value(obj, key)
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            return value
        raise LLMServiceError.bad_gateway(message)

    @staticmethod
    def _get_value(obj: Any, key: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, Mapping):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @staticmethod
    def _first_item(items: Any) -> Any:
        if isinstance(items, Sequence) and not isinstance(items, str | bytes | bytearray) and items:
            return items[0]
        if isinstance(items, Iterable) and not isinstance(items, str | bytes | bytearray):
            iterator = iter(items)
            return next(iterator, None)
        return None

    @staticmethod
    def _to_optional_str(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return str(value)

    @staticmethod
    def _to_optional_int(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: Any, *, default: int) -> int:
        parsed = LLMService._to_optional_int(value)
        if parsed is None:
            return default
        return parsed

    @staticmethod
    def _to_optional_float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


@lru_cache
def get_default_llm_service() -> LLMService:
    return LLMService()
