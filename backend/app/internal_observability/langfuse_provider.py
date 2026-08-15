"""Internal Langfuse observability provider."""

from __future__ import annotations

import importlib
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from typing import Any, Protocol, cast

from cogmait_shared.observability.logging import logger

from ..observability.context import ObservabilityContext
from ..observability.sanitizer import ObservabilitySanitizer


class LangfuseSettingsProtocol(Protocol):
    langfuse_base_url: str | None
    langfuse_host: str | None
    langfuse_public_key: str | None
    langfuse_secret_key: str | None
    observability_env: str
    observability_service_name: str


class LangfuseObservabilityProvider:
    """Langfuse adapter for internal development environments."""

    def __init__(
        self,
        *,
        config: LangfuseSettingsProtocol,
        sanitizer: ObservabilitySanitizer,
        client: Any | None = None,
    ) -> None:
        self._config = config
        self._sanitizer = sanitizer
        self._client = client or self._build_client(config)

    @contextmanager
    def trace(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Iterator[ObservabilityContext]:
        sanitized = self._sanitize_event(name=name, metadata=metadata, extra=kwargs)
        with self._start_observation(
            sanitized,
            legacy_method="trace",
            use_trace_context=True,
        ) as observation:
            self._update_current_trace(sanitized)
            yield self._context_from_observation(observation)

    @contextmanager
    def span(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Iterator[ObservabilityContext]:
        sanitized = self._sanitize_event(name=name, metadata=metadata, extra=kwargs)
        with self._start_observation(
            sanitized,
            legacy_method="span",
            use_trace_context=False,
        ) as observation:
            yield self._context_from_observation(observation)

    def record_llm_call(self, payload: dict[str, Any]) -> None:
        # LLM generations are emitted by LiteLLM's langfuse_otel callback.
        del payload

    def record_embedding(self, payload: dict[str, Any]) -> None:
        # Embedding calls also go through LiteLLM and must not be duplicated here.
        del payload

    def record_tool_call(self, payload: dict[str, Any]) -> None:
        self._record_span_payload({**payload, "type": "tool_call"})

    def record_workflow_node(self, payload: dict[str, Any]) -> None:
        self._record_span_payload({**payload, "type": "workflow_node"})

    def record_agent_step(self, payload: dict[str, Any]) -> None:
        self._record_span_payload({**payload, "type": "agent_step"})

    def record_error(self, error: Exception, metadata: dict[str, Any] | None = None) -> None:
        payload = {
            "name": error.__class__.__name__,
            "level": "ERROR",
            "status_message": _safe_error_status_message(error),
            "metadata": metadata or {},
        }
        self._record_event_payload(payload)

    def update_current_trace(self, metadata: dict[str, Any] | None = None) -> None:
        sanitized = self._sanitizer.sanitize_payload(
            {
                "metadata": {
                    "environment": self._config.observability_env,
                    "service_name": self._config.observability_service_name,
                    **(metadata or {}),
                }
            }
        )
        self._update_current_trace(sanitized)

    def flush(self) -> None:
        self._safe_call("flush")

    def shutdown(self) -> None:
        shutdown = getattr(self._client, "shutdown", None)
        if callable(shutdown):
            self._safe_call("shutdown")
            return
        self.flush()

    def _record_span_payload(self, payload: Mapping[str, Any]) -> None:
        sanitized = self._sanitizer.sanitize_payload(payload)
        if "name" not in sanitized:
            sanitized["name"] = "span"
        with self._start_observation(
            sanitized,
            legacy_method="span",
            use_trace_context=False,
        ):
            return

    def _record_event_payload(self, payload: dict[str, Any]) -> None:
        sanitized = self._sanitizer.sanitize_payload(payload)
        if "name" not in sanitized:
            sanitized["name"] = "event"
        create_event = getattr(self._client, "create_event", None)
        if callable(create_event):
            self._safe_call(
                "create_event",
                **self._langfuse_v3_observation_kwargs(sanitized, use_trace_context=True),
            )
            return
        self._safe_call("event", **sanitized)

    @contextmanager
    def _start_observation(
        self,
        payload: dict[str, Any],
        *,
        legacy_method: str,
        use_trace_context: bool,
    ) -> Iterator[Any]:
        start_as_current_span = getattr(self._client, "start_as_current_span", None)
        if callable(start_as_current_span):
            with self._start_v3_span(
                start_as_current_span,
                payload,
                use_trace_context=use_trace_context,
            ) as span:
                yield span
            return

        observation = self._safe_call(legacy_method, **payload)
        yield observation

    @contextmanager
    def _start_v3_span(
        self,
        start_as_current_span: Any,
        payload: dict[str, Any],
        *,
        use_trace_context: bool,
    ) -> Iterator[Any]:
        try:
            span_manager = cast(
                AbstractContextManager[Any],
                start_as_current_span(
                    **self._langfuse_v3_observation_kwargs(
                        payload,
                        use_trace_context=use_trace_context,
                    )
                ),
            )
        except Exception as exc:  # pragma: no cover - defensive guard around SDK errors
            logger.opt(exception=exc).warning("Langfuse observability 写入失败")
            yield None
            return

        exit_args: tuple[type[BaseException] | None, BaseException | None, Any | None] = (
            None,
            None,
            None,
        )
        try:
            span = span_manager.__enter__()
        except Exception as exc:  # pragma: no cover - defensive guard around SDK errors
            logger.opt(exception=exc).warning("Langfuse observability 写入失败")
            yield None
            return

        try:
            yield span
        except BaseException as exc:
            exit_args = (type(exc), exc, exc.__traceback__)
            raise
        finally:
            try:
                span_manager.__exit__(*exit_args)
            except Exception as exc:  # pragma: no cover - defensive guard around SDK errors
                logger.opt(exception=exc).warning("Langfuse observability 写入失败")

    def _update_current_trace(self, payload: dict[str, Any]) -> None:
        update_current_trace = getattr(self._client, "update_current_trace", None)
        if not callable(update_current_trace):
            return
        kwargs: dict[str, Any] = {"metadata": payload.get("metadata")}
        if payload.get("name") is not None:
            kwargs["name"] = payload.get("name")
        kwargs.update(self._trace_attributes_from_metadata(payload.get("metadata")))
        self._safe_call("update_current_trace", **kwargs)

    @staticmethod
    def _trace_attributes_from_metadata(metadata: Any) -> dict[str, Any]:
        if not isinstance(metadata, Mapping):
            return {}
        result: dict[str, Any] = {}
        session_id = metadata.get("langfuse_session_id")
        if isinstance(session_id, str) and session_id:
            result["session_id"] = session_id
        user_id = metadata.get("langfuse_user_id") or metadata.get("trace_user_id")
        if isinstance(user_id, str) and user_id:
            result["user_id"] = user_id
        tags = metadata.get("langfuse_tags") or metadata.get("tags")
        if isinstance(tags, list) and all(isinstance(item, str) for item in tags):
            result["tags"] = tags
        return result

    @staticmethod
    def _langfuse_v3_observation_kwargs(
        payload: dict[str, Any],
        *,
        use_trace_context: bool,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": payload.get("name"),
            "metadata": payload.get("metadata"),
        }
        trace_context = (
            LangfuseObservabilityProvider._trace_context_from_metadata(payload.get("metadata"))
            if use_trace_context
            else None
        )
        if trace_context is not None:
            result["trace_context"] = trace_context
        for key in ("input", "output", "version", "level", "status_message"):
            if key in payload:
                result[key] = payload[key]
        return {key: value for key, value in result.items() if value is not None}

    @staticmethod
    def _trace_context_from_metadata(metadata: Any) -> dict[str, str] | None:
        if not isinstance(metadata, Mapping):
            return None
        trace_id = metadata.get("trace_id")
        if not isinstance(trace_id, str) or not trace_id:
            return None
        result = {"trace_id": trace_id}
        parent_span_id = metadata.get("parent_span_id")
        if isinstance(parent_span_id, str) and parent_span_id:
            result["parent_span_id"] = parent_span_id
        return result

    def _sanitize_event(
        self,
        *,
        name: str,
        metadata: dict[str, Any] | None,
        extra: Mapping[str, Any],
    ) -> dict[str, Any]:
        raw_payload: dict[str, Any] = {
            "name": name,
            "metadata": {
                "environment": self._config.observability_env,
                "service_name": self._config.observability_service_name,
                **(metadata or {}),
            },
            **dict(extra),
        }
        return self._sanitizer.sanitize_payload(raw_payload)

    def _safe_call(self, method_name: str, **kwargs: Any) -> Any:
        method = getattr(self._client, method_name, None)
        if not callable(method):
            return None
        try:
            return method(**kwargs)
        except Exception as exc:  # pragma: no cover - defensive guard around SDK/network errors
            logger.opt(exception=exc).warning("Langfuse observability 写入失败")
            return None

    @staticmethod
    def _context_from_observation(observation: Any) -> ObservabilityContext:
        return ObservabilityContext(
            trace_id=LangfuseObservabilityProvider._get_attr(observation, "trace_id"),
            span_id=LangfuseObservabilityProvider._get_attr(observation, "id"),
            parent_span_id=LangfuseObservabilityProvider._get_attr(
                observation,
                "parent_observation_id",
            ),
        )

    @staticmethod
    def _get_attr(obj: Any, name: str) -> str | None:
        value = getattr(obj, name, None)
        return value if isinstance(value, str) and value else None

    @staticmethod
    def _build_client(config: LangfuseSettingsProtocol) -> Any:
        langfuse_module = importlib.import_module("langfuse")
        langfuse_cls = getattr(langfuse_module, "Langfuse")
        host = config.langfuse_base_url or config.langfuse_host
        if not host:
            raise ValueError("启用 Langfuse 需要配置 LANGFUSE_BASE_URL")
        if not config.langfuse_public_key or not config.langfuse_secret_key:
            raise ValueError("启用 Langfuse 需要配置 LANGFUSE_PUBLIC_KEY 和 LANGFUSE_SECRET_KEY")
        kwargs = {
            "public_key": config.langfuse_public_key,
            "secret_key": config.langfuse_secret_key,
            "host": host,
            "environment": config.observability_env,
        }
        return langfuse_cls(**{key: value for key, value in kwargs.items() if value})


def _safe_error_status_message(error: Exception) -> str:
    parts = [error.__class__.__name__]
    status_code = getattr(error, "status_code", None)
    code = getattr(error, "code", None)
    if isinstance(status_code, int):
        parts.append(f"status_code={status_code}")
    if isinstance(code, int):
        parts.append(f"code={code}")
    return " ".join(parts)
