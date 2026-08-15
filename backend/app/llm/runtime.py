"""LiteLLM runtime wrapper for ai_service."""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Iterable
from typing import Any, Protocol

import httpx

from cogmait_shared.observability.logging import route_std_loggers_to_root

from ..core.config import settings
from ..observability.provider_name import ObservabilityProviderName

__all__ = ["LiteLLMRuntime", "LiteLLMRuntimeError"]


class LiteLLMRuntimeError(RuntimeError):
    """LiteLLM 运行时异常。"""


class LiteLLMConfigProtocol(Protocol):
    litellm_api_base: str | None
    litellm_api_key: str | None
    litellm_timeout: float
    litellm_num_retries: int
    observability_enabled: bool
    observability_env: str
    observability_service_name: str
    observability_capture_prompt: bool
    observability_capture_response: bool
    observability_litellm_message_logging_enabled: bool
    langfuse_base_url: str | None
    langfuse_host: str | None
    langfuse_public_key: str | None
    langfuse_secret_key: str | None

    @property
    def observability_provider(self) -> ObservabilityProviderName | str: ...


class LiteLLMRuntime:
    """唯一直接调用 LiteLLM 的位置。"""

    def __init__(
        self,
        *,
        config: LiteLLMConfigProtocol = settings,
        litellm_module: Any | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._litellm = litellm_module
        self._http_transport = http_transport
        self._langfuse_callback_configured = False

    async def acompletion(self, **kwargs: Any) -> Any:
        litellm = self._load_litellm()
        return await litellm.acompletion(**self._build_call_kwargs(kwargs))

    async def aembedding(self, **kwargs: Any) -> Any:
        litellm = self._load_litellm()
        return await litellm.aembedding(
            **self._build_call_kwargs(self._apply_embedding_provider_compatibility(kwargs))
        )

    async def arerank(self, **kwargs: Any) -> Any:
        litellm = self._load_litellm()
        return await litellm.arerank(**self._build_call_kwargs(kwargs))

    async def list_embedding_models(self) -> list[str]:
        litellm = self._load_litellm()
        raw_models = getattr(litellm, "all_embedding_models", ())
        return sorted(self._normalize_model_names(raw_models))

    async def list_completion_models(self) -> list[str]:
        if self._config.litellm_api_base:
            return await self._list_proxy_completion_models()
        return self._list_local_completion_models()

    async def _list_proxy_completion_models(self) -> list[str]:
        base_url = self._normalize_api_base(self._config.litellm_api_base)
        if not base_url:
            return []

        headers = {}
        if self._config.litellm_api_key:
            headers["Authorization"] = f"Bearer {self._config.litellm_api_key}"

        async with httpx.AsyncClient(
            timeout=self._config.litellm_timeout,
            transport=self._http_transport,
        ) as client:
            last_error: Exception | None = None
            for url in self._model_list_urls(base_url):
                try:
                    response = await client.get(url, headers=headers)
                    if response.status_code == 404:
                        continue
                    response.raise_for_status()
                    return self._extract_completion_model_names(response.json())
                except httpx.HTTPError as exc:
                    last_error = exc
                    continue
                except ValueError as exc:
                    raise LiteLLMRuntimeError("LiteLLM 模型列表返回非法 JSON") from exc

        if last_error is not None:
            raise LiteLLMRuntimeError(
                f"LiteLLM 已部署模型列表获取失败：{last_error}"
            ) from last_error
        raise LiteLLMRuntimeError("LiteLLM 已部署模型列表不可用")

    def _list_local_completion_models(self) -> list[str]:
        litellm = self._load_litellm()
        raw_models = self._first_model_collection(
            getattr(litellm, "all_llm_models", None) or getattr(litellm, "model_list", None),
            getattr(litellm, "open_ai_chat_completion_models", ()),
        )
        excluded = set(self._normalize_model_names(getattr(litellm, "all_embedding_models", ())))
        return sorted(
            model for model in self._normalize_model_names(raw_models) if model not in excluded
        )

    def _load_litellm(self) -> Any:
        if self._litellm is None:
            os.environ.setdefault("LITELLM_LOG", "INFO")
            import litellm

            self._litellm = litellm

        self._normalize_litellm_logging()
        self._configure_langfuse_callback_once(self._litellm)
        return self._litellm

    @staticmethod
    def _normalize_litellm_logging() -> None:
        route_std_loggers_to_root("LiteLLM", "LiteLLM Proxy", "LiteLLM Router")

    @staticmethod
    def _first_model_collection(*candidates: object) -> tuple[str, ...] | list[str] | set[str]:
        for candidate in candidates:
            if isinstance(candidate, list | set | tuple):
                return candidate
        return ()

    @staticmethod
    def _normalize_model_names(raw_models: object) -> set[str]:
        if not isinstance(raw_models, list | set | tuple):
            return set()
        return {model.strip() for model in raw_models if isinstance(model, str) and model.strip()}

    @staticmethod
    def _normalize_api_base(value: str | None) -> str:
        return (value or "").strip().rstrip("/")

    @classmethod
    def _model_list_urls(cls, base_url: str) -> list[str]:
        if base_url.endswith("/v1"):
            root_url = base_url[: -len("/v1")]
            return [
                f"{base_url}/model/info",
                f"{root_url}/model/info",
                f"{base_url}/models",
                f"{root_url}/models",
            ]
        return [
            f"{base_url}/model/info",
            f"{base_url}/v1/model/info",
            f"{base_url}/models",
            f"{base_url}/v1/models",
        ]

    @classmethod
    def _extract_completion_model_names(cls, payload: object) -> list[str]:
        items = cls._extract_model_items(payload)
        names = {
            name
            for item in items
            if cls._is_completion_model_item(item)
            for name in [cls._extract_model_name(item)]
            if name
        }
        return sorted(names)

    @classmethod
    def _extract_model_items(cls, payload: object) -> Iterable[object]:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return ()
        for key in ("data", "models", "model_list"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return ()

    @classmethod
    def _extract_model_name(cls, item: object) -> str | None:
        if isinstance(item, str):
            normalized = item.strip()
            return normalized or None
        if not isinstance(item, dict):
            return None
        for key in ("id", "model_name", "model", "litellm_model_name"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @classmethod
    def _is_completion_model_item(cls, item: object) -> bool:
        if not isinstance(item, dict):
            return True
        mode = cls._extract_model_mode(item)
        if not mode:
            return True
        return mode in {"chat", "completion", "llm"}

    @classmethod
    def _extract_model_mode(cls, item: dict[str, object]) -> str | None:
        candidates: list[object] = [item.get("mode"), item.get("model_type")]
        model_info = item.get("model_info")
        if isinstance(model_info, dict):
            candidates.extend(
                [
                    model_info.get("mode"),
                    model_info.get("model_type"),
                    model_info.get("input_type"),
                ]
            )
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip().lower()
        return None

    def _build_call_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        payload = dict(kwargs)
        model = payload.get("model")
        if isinstance(model, str):
            payload["model"] = self._normalize_model_name(model)
        if payload.get("timeout") is None:
            payload["timeout"] = self._config.litellm_timeout
        if payload.get("num_retries") is None:
            payload["num_retries"] = self._config.litellm_num_retries
        if payload.get("api_base") is None and self._config.litellm_api_base:
            payload["api_base"] = self._config.litellm_api_base
        if payload.get("api_key") is None and self._config.litellm_api_key:
            payload["api_key"] = self._config.litellm_api_key
        return {key: value for key, value in payload.items() if value is not None}

    def _apply_embedding_provider_compatibility(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        payload = dict(kwargs)
        api_base = payload.get("api_base") or self._config.litellm_api_base
        if (
            "encoding_format" not in payload
            and isinstance(api_base, str)
            and self._is_dashscope_api_base(api_base)
        ):
            payload["encoding_format"] = "float"
        return payload

    @staticmethod
    def _is_dashscope_api_base(api_base: str) -> bool:
        return "dashscope.aliyuncs.com" in api_base.strip().lower()
    def _normalize_model_name(self, model: str) -> str:
        """配置了 Proxy 时，将 sys_config 中的模型名转为 OpenAI 兼容路由。

        业务侧（问数、基准评价、改写等）统一只填 Proxy `/v1/models` 返回的 model id，
        例如 ``bailian/qwen3.6-plus`` 或 ``qwen3-30b-a3b-instruct-2507``。
        """
        normalized = model.strip()
        if not normalized or not self._config.litellm_api_base:
            return normalized
        if normalized.startswith("openai/"):
            return normalized
        return f"openai/{normalized}"

    def _configure_langfuse_callback_once(self, litellm: Any) -> None:
        if self._langfuse_callback_configured:
            return
        self._configure_langfuse_callback(litellm)
        self._langfuse_callback_configured = True

    def _configure_langfuse_callback(self, litellm: Any) -> None:
        if not self._should_enable_langfuse_callback():
            return
        langfuse_url = self._langfuse_url()
        if not self._has_langfuse_otel_dependencies():
            raise LiteLLMRuntimeError("启用 Langfuse 需要安装 ai_service 的 observability 依赖")

        public_key = self._config.langfuse_public_key
        secret_key = self._config.langfuse_secret_key
        if public_key is None or secret_key is None:
            return

        os.environ["LANGFUSE_PUBLIC_KEY"] = public_key
        os.environ["LANGFUSE_SECRET_KEY"] = secret_key
        os.environ["LANGFUSE_BASE_URL"] = langfuse_url
        os.environ["LANGFUSE_HOST"] = langfuse_url
        os.environ["LANGFUSE_OTEL_HOST"] = langfuse_url
        os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = self._config.observability_env
        os.environ["OTEL_RESOURCE_ATTRIBUTES"] = self._merge_otel_resource_attributes(
            os.environ.get("OTEL_RESOURCE_ATTRIBUTES"),
            {
                "langfuse.environment": self._config.observability_env,
                "service.name": self._config.observability_service_name,
                "deployment.environment": self._config.observability_env,
            },
        )

        callbacks = getattr(litellm, "callbacks", [])
        if not isinstance(callbacks, list):
            callbacks = list(callbacks) if isinstance(callbacks, tuple | set) else []
        if "langfuse_otel" not in callbacks:
            callbacks.append("langfuse_otel")
        litellm.callbacks = callbacks

        # Raw LiteLLM messages include both prompt and response.
        message_logging_enabled = self._should_enable_litellm_message_logging()
        litellm.turn_off_message_logging = not message_logging_enabled
        litellm.message_logging = message_logging_enabled

    def _should_enable_litellm_message_logging(self) -> bool:
        return bool(self._config.observability_litellm_message_logging_enabled)

    def _should_enable_langfuse_callback(self) -> bool:
        return (
            self._config.observability_enabled
            and self._config.observability_provider == ObservabilityProviderName.LANGFUSE
            and bool(self._config.langfuse_public_key)
            and bool(self._config.langfuse_secret_key)
        )

    def _langfuse_url(self) -> str:
        langfuse_url = self._config.langfuse_base_url or self._config.langfuse_host
        if not langfuse_url:
            raise LiteLLMRuntimeError("启用 Langfuse 需要配置 LANGFUSE_BASE_URL")
        return langfuse_url

    @staticmethod
    def _has_langfuse_otel_dependencies() -> bool:
        return (
            importlib.util.find_spec("opentelemetry") is not None
            and importlib.util.find_spec("opentelemetry.sdk") is not None
            and importlib.util.find_spec("opentelemetry.exporter.otlp") is not None
        )

    @staticmethod
    def _merge_otel_resource_attributes(
        current: str | None,
        updates: dict[str, str],
    ) -> str:
        attributes: dict[str, str] = {}
        for raw_item in (current or "").split(","):
            item = raw_item.strip()
            if not item or "=" not in item:
                continue
            key, value = item.split("=", 1)
            if key.strip():
                attributes[key.strip()] = value.strip()
        attributes.update(updates)
        return ",".join(f"{key}={value}" for key, value in attributes.items())
