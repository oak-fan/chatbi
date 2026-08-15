"""Observability provider factory."""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from cogmait_shared.observability.logging import logger

from .base import ObservabilityProvider
from .noop_provider import NoopObservabilityProvider
from .provider_name import ObservabilityProviderName
from .sanitizer import ObservabilitySanitizer


class ObservabilitySettingsProtocol(Protocol):
    observability_enabled: bool
    observability_capture_prompt: bool
    observability_capture_response: bool
    observability_capture_tool_args: bool
    observability_mask_user_id: bool
    observability_env: str
    observability_service_name: str
    langfuse_base_url: str | None
    langfuse_host: str | None
    langfuse_public_key: str | None
    langfuse_secret_key: str | None

    @property
    def observability_provider(self) -> ObservabilityProviderName | str: ...


def build_observability_provider(
    config: ObservabilitySettingsProtocol,
) -> ObservabilityProvider:
    """Build the configured observability provider."""

    if not config.observability_enabled:
        return NoopObservabilityProvider()

    provider = config.observability_provider
    if provider == ObservabilityProviderName.NOOP:
        return NoopObservabilityProvider()
    if provider == ObservabilityProviderName.LANGFUSE:
        return _build_langfuse_provider(config)
    raise ValueError(f"不支持的 OBSERVABILITY_PROVIDER：{config.observability_provider}")


@lru_cache
def get_default_observability_provider() -> ObservabilityProvider:
    """Return the process-level default observability provider."""

    from ..core.config import settings

    return build_observability_provider(settings)


def shutdown_default_observability_provider() -> None:
    """Shutdown the process-level provider when it has already been initialized."""

    if get_default_observability_provider.cache_info().currsize == 0:
        return
    provider = get_default_observability_provider()
    try:
        provider.shutdown()
    except Exception as exc:
        logger.opt(exception=exc).warning("Observability Provider 关闭失败")
    finally:
        get_default_observability_provider.cache_clear()


def _build_langfuse_provider(config: ObservabilitySettingsProtocol) -> ObservabilityProvider:
    sanitizer = ObservabilitySanitizer(config=config)
    from ..internal_observability.langfuse_provider import LangfuseObservabilityProvider

    return LangfuseObservabilityProvider(config=config, sanitizer=sanitizer)
