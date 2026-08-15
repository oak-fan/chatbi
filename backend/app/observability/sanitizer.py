"""Observability payload sanitizer."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Protocol

_EMAIL_RE = re.compile(
    r"(?P<name>[A-Za-z0-9._%+-])[^@\s]*@(?P<domain>[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
_API_KEY_RE = re.compile(r"\b(sk|ak)-[A-Za-z0-9_\-]{6,}\b")

_PROMPT_KEYS = {"prompt", "prompts", "messages", "input", "inputs", "content"}
_RESPONSE_KEYS = {"response", "responses", "output", "outputs", "completion"}
_TOOL_ARG_KEYS = {"tool_args", "toolargs", "arguments", "params", "parameters"}
_IDENTITY_KEYS = {"user_id", "userid", "tenant_id", "tenantid"}
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "secret_key",
    "secretkey",
    "token",
}


class SanitizerConfigProtocol(Protocol):
    observability_capture_prompt: bool
    observability_capture_response: bool
    observability_capture_tool_args: bool
    observability_mask_user_id: bool


class ObservabilitySanitizer:
    """Sanitize observability payloads before provider writes."""

    def __init__(self, *, config: SanitizerConfigProtocol, max_text_length: int = 2048) -> None:
        self._config = config
        self._max_text_length = max_text_length

    def sanitize_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Return a sanitized copy of a mapping payload."""

        return self._sanitize_mapping(payload)

    def _sanitize_mapping(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in payload.items():
            key = str(raw_key)
            normalized_key = self._normalize_key(key)
            if self._should_drop_key(normalized_key):
                continue
            sanitized[key] = self._sanitize_value(normalized_key, raw_value)
        return sanitized

    def _sanitize_value(self, normalized_key: str, value: Any) -> Any:
        if normalized_key in _SECRET_KEYS:
            return "****redacted****"
        if normalized_key in _IDENTITY_KEYS and self._config.observability_mask_user_id:
            return self._hash_identity(value)
        if isinstance(value, Mapping):
            return self._sanitize_mapping(value)
        if isinstance(value, list):
            return [self._sanitize_value(normalized_key, item) for item in value]
        if isinstance(value, tuple):
            return [self._sanitize_value(normalized_key, item) for item in value]
        if isinstance(value, str):
            return self._sanitize_text(value)
        return value

    def _sanitize_text(self, value: str) -> str:
        masked = _EMAIL_RE.sub(
            lambda match: f"{match.group('name')}***@{match.group('domain')}",
            value,
        )
        masked = _PHONE_RE.sub(r"\1****\2", masked)
        masked = _API_KEY_RE.sub(r"\1-****redacted****", masked)
        if len(masked) <= self._max_text_length:
            return masked
        return f"{masked[: self._max_text_length]}..."

    def _should_drop_key(self, normalized_key: str) -> bool:
        if normalized_key in _PROMPT_KEYS and not self._config.observability_capture_prompt:
            return True
        if normalized_key in _RESPONSE_KEYS and not self._config.observability_capture_response:
            return True
        return normalized_key in _TOOL_ARG_KEYS and not self._config.observability_capture_tool_args

    @staticmethod
    def _normalize_key(key: str) -> str:
        return key.replace("-", "_").lower()

    @staticmethod
    def _hash_identity(value: Any) -> str | None:
        if value is None:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"hash_{digest}"
