"""ai_service 内部 LLM 请求与返回结构。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Message:
    role: str
    content: Any

    def __post_init__(self) -> None:
        self.role = _normalize_required_string(self.role, field_name="role")


@dataclass(slots=True)
class CompletionRequest:
    messages: list[Message]
    model: str | None = None
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    stop: str | list[str] | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    tool_choice: str | dict[str, Any] | None = None
    timeout: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    provider_options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.model = _normalize_optional_string(self.model)
        self.messages = _normalize_message_list(self.messages)
        self.stream = _normalize_bool(self.stream, field_name="stream")
        self.temperature = _normalize_optional_float(self.temperature, field_name="temperature")
        self.max_tokens = _normalize_optional_int(self.max_tokens, field_name="max_tokens")
        self.top_p = _normalize_optional_float(self.top_p, field_name="top_p")
        self.stop = _normalize_stop(self.stop)
        self.tools = _normalize_mapping_list(self.tools, field_name="tools")
        self.tool_choice = _normalize_tool_choice(self.tool_choice)
        self.timeout = _normalize_optional_float(self.timeout, field_name="timeout")
        self.metadata = _normalize_mapping(self.metadata, field_name="metadata")
        self.provider_options = _normalize_mapping(
            self.provider_options,
            field_name="provider_options",
        )


@dataclass(slots=True)
class EmbeddingRequest:
    input_texts: list[str]
    model: str | None = None
    dimensions: int | None = None
    timeout: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    provider_options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.model = _normalize_optional_string(self.model)
        self.input_texts = _normalize_string_list(
            self.input_texts,
            field_name="input_texts",
            allow_empty=False,
        )
        self.dimensions = _normalize_optional_int(self.dimensions, field_name="dimensions")
        self.timeout = _normalize_optional_float(self.timeout, field_name="timeout")
        self.metadata = _normalize_mapping(self.metadata, field_name="metadata")
        self.provider_options = _normalize_mapping(
            self.provider_options,
            field_name="provider_options",
        )


@dataclass(slots=True)
class RerankRequest:
    query: str
    documents: list[Any]
    model: str | None = None
    top_n: int | None = None
    return_documents: bool = True
    timeout: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    provider_options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.model = _normalize_optional_string(self.model)
        self.query = _normalize_required_string(self.query, field_name="query")
        self.top_n = _normalize_optional_int(self.top_n, field_name="top_n")
        self.return_documents = _normalize_bool(
            self.return_documents,
            field_name="return_documents",
        )
        self.documents = _normalize_iterable_to_list(
            self.documents,
            field_name="documents",
            allow_empty=False,
        )
        self.timeout = _normalize_optional_float(self.timeout, field_name="timeout")
        self.metadata = _normalize_mapping(self.metadata, field_name="metadata")
        self.provider_options = _normalize_mapping(
            self.provider_options,
            field_name="provider_options",
        )


@dataclass(slots=True)
class UsageInfo:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(slots=True)
class EmbeddingModelOption:
    label: str
    value: str

    def __post_init__(self) -> None:
        self.label = _normalize_required_string(self.label, field_name="label")
        self.value = _normalize_required_string(self.value, field_name="value")


@dataclass(slots=True)
class CompletionModelOption:
    label: str
    value: str

    def __post_init__(self) -> None:
        self.label = _normalize_required_string(self.label, field_name="label")
        self.value = _normalize_required_string(self.value, field_name="value")


@dataclass(slots=True)
class CompletionChoice:
    index: int
    message: Message
    finish_reason: str | None = None


@dataclass(slots=True)
class CompletionResponse:
    model: str
    choices: list[CompletionChoice]
    usage: UsageInfo | None = None


@dataclass(slots=True)
class CompletionChunk:
    delta: str | dict[str, Any]
    finish_reason: str | None = None


@dataclass(slots=True)
class EmbeddingResponse:
    model: str
    embeddings: list[list[float]]
    dimensions: int
    usage: UsageInfo | None = None


@dataclass(slots=True)
class RerankItem:
    index: int
    document: Any | None = None
    score: float | None = None


@dataclass(slots=True)
class RerankResponse:
    model: str
    results: list[RerankItem] = field(default_factory=list)


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("model 必须为字符串")
    normalized = value.strip()
    return normalized or None


def _normalize_required_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须为字符串")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} 不能为空")
    return normalized


def _normalize_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} 必须为布尔值")
    return value


def _normalize_optional_float(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} 必须为数字")
    return float(value)


def _normalize_optional_int(value: Any, *, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} 必须为整数")
    return value


def _normalize_iterable_to_list(
    value: Any,
    *,
    field_name: str,
    allow_empty: bool,
) -> list[Any]:
    if isinstance(value, str | bytes | bytearray) or not isinstance(value, Iterable):
        raise ValueError(f"{field_name} 必须为列表")
    normalized = list(value)
    if not allow_empty and not normalized:
        raise ValueError(f"{field_name} 不能为空")
    return normalized


def _normalize_message_list(value: Any) -> list[Message]:
    messages = _normalize_iterable_to_list(value, field_name="messages", allow_empty=False)
    for item in messages:
        if not isinstance(item, Message):
            raise ValueError("messages 必须为 Message 列表")
    return messages


def _normalize_string_list(
    value: Any,
    *,
    field_name: str,
    allow_empty: bool,
) -> list[str]:
    items = _normalize_iterable_to_list(value, field_name=field_name, allow_empty=allow_empty)
    normalized: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} 必须为字符串列表")
        normalized.append(item)
    return normalized


def _normalize_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} 必须为对象")
    return dict(value)


def _normalize_mapping_list(value: Any, *, field_name: str) -> list[dict[str, Any]]:
    items = _normalize_iterable_to_list(value, field_name=field_name, allow_empty=True)
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError(f"{field_name} 必须为对象列表")
        normalized.append(dict(item))
    return normalized


def _normalize_stop(value: Any) -> str | list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return _normalize_string_list(value, field_name="stop", allow_empty=True)
    raise ValueError("stop 必须为字符串或字符串列表")


def _normalize_tool_choice(value: Any) -> str | dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return dict(value)
    raise ValueError("tool_choice 必须为字符串或对象")
