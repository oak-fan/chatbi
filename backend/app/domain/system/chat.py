"""Chat 领域对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from cogmait_shared.core.datetime_utils import ensure_timezone, now_local

from ...constants.chat import (
    CHAT_DEFAULT_PAGE_SIZE,
    CHAT_DEFAULT_TOP_K,
    CHAT_FEEDBACK_RATING_DISLIKE,
    CHAT_FEEDBACK_RATING_LIKE,
    CHAT_FEEDBACK_STATUS_IGNORED,
    CHAT_FEEDBACK_STATUS_OPEN,
    CHAT_FEEDBACK_STATUS_RESOLVED,
    CHAT_FEEDBACK_STATUS_REVIEWED,
    CHAT_MAX_APP_DESCRIPTION_LENGTH,
    CHAT_MAX_FEEDBACK_ADMIN_NOTE_LENGTH,
    CHAT_MAX_FEEDBACK_COMMENT_LENGTH,
    CHAT_MAX_FEEDBACK_EVAL_NOTE_LENGTH,
    CHAT_MAX_FEEDBACK_HANDLER_KEY_LENGTH,
    CHAT_MAX_FEEDBACK_TYPE_CODE_LENGTH,
    CHAT_MAX_FEEDBACK_TYPE_DESCRIPTION_LENGTH,
    CHAT_MAX_FEEDBACK_TYPE_LABEL_LENGTH,
    CHAT_MAX_MESSAGE_LENGTH,
    CHAT_MAX_MODEL_LENGTH,
    CHAT_MAX_PAGE_SIZE,
    CHAT_MAX_PROJECT_NAME_LENGTH,
    CHAT_MAX_SYSTEM_PROMPT_LENGTH,
    CHAT_MAX_TITLE_LENGTH,
    CHAT_MAX_TOP_K,
    CHAT_MESSAGE_ROLE_ASSISTANT,
    CHAT_MESSAGE_ROLE_SYSTEM,
    CHAT_MESSAGE_ROLE_USER,
    CHAT_MESSAGE_STATUS_FAILED,
    CHAT_MESSAGE_STATUS_SUCCESS,
    CHAT_RUN_MODE_AUTO,
    CHAT_RUN_MODE_FILE_CHAT,
    CHAT_RUN_MODE_KNOWLEDGE_RAG,
    CHAT_RUN_MODE_LLM_CHAT,
    CHAT_STREAM_EVENT_CITATIONS,
    CHAT_STREAM_EVENT_COMPLETED,
    CHAT_STREAM_EVENT_DELTA,
    CHAT_STREAM_EVENT_FAILED,
    CHAT_STREAM_EVENT_PARSING,
    CHAT_STREAM_EVENT_RETRIEVING,
    CHAT_STREAM_EVENT_STARTED,
)
from .retrieval import RetrievalConfig

CHAT_OPERATION_DEFAULT_WINDOW_DAYS = 7
CHAT_OPERATION_MAX_WINDOW_DAYS = 90
CHAT_OPERATION_DEFAULT_RECENT_ERROR_LIMIT = 5
CHAT_OPERATION_MAX_RECENT_ERROR_LIMIT = 20


class ChatRunMode(StrEnum):
    """Chat 运行模式。"""

    LLM_CHAT = CHAT_RUN_MODE_LLM_CHAT
    KNOWLEDGE_RAG = CHAT_RUN_MODE_KNOWLEDGE_RAG
    FILE_CHAT = CHAT_RUN_MODE_FILE_CHAT
    AUTO = CHAT_RUN_MODE_AUTO


class ChatMessageRole(StrEnum):
    """Chat 消息角色。"""

    USER = CHAT_MESSAGE_ROLE_USER
    ASSISTANT = CHAT_MESSAGE_ROLE_ASSISTANT
    SYSTEM = CHAT_MESSAGE_ROLE_SYSTEM


class ChatMessageStatus(StrEnum):
    """Chat 消息状态。"""

    SUCCESS = CHAT_MESSAGE_STATUS_SUCCESS
    FAILED = CHAT_MESSAGE_STATUS_FAILED


class ChatFeedbackRating(StrEnum):
    """Chat 反馈评分。"""

    LIKE = CHAT_FEEDBACK_RATING_LIKE
    DISLIKE = CHAT_FEEDBACK_RATING_DISLIKE


class ChatFeedbackStatus(StrEnum):
    """Chat 反馈处理状态。"""

    OPEN = CHAT_FEEDBACK_STATUS_OPEN
    REVIEWED = CHAT_FEEDBACK_STATUS_REVIEWED
    RESOLVED = CHAT_FEEDBACK_STATUS_RESOLVED
    IGNORED = CHAT_FEEDBACK_STATUS_IGNORED


class ChatStreamEventType(StrEnum):
    """Chat 流式事件类型。"""

    STARTED = CHAT_STREAM_EVENT_STARTED
    PARSING = CHAT_STREAM_EVENT_PARSING
    RETRIEVING = CHAT_STREAM_EVENT_RETRIEVING
    CITATIONS = CHAT_STREAM_EVENT_CITATIONS
    DELTA = CHAT_STREAM_EVENT_DELTA
    COMPLETED = CHAT_STREAM_EVENT_COMPLETED
    FAILED = CHAT_STREAM_EVENT_FAILED


def _normalize_required_str(value: str, *, field_name: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须为字符串")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} 不能为空")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} 长度不能超过 {max_length}")
    return normalized


def _normalize_optional_str(value: str | None, *, field_name: str, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须为字符串")
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} 长度不能超过 {max_length}")
    return normalized


def _normalize_positive_int(value: int, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} 必须为正整数")
    return value


def _normalize_optional_positive_int(value: int | None, *, field_name: str) -> int | None:
    if value is None:
        return None
    return _normalize_positive_int(value, field_name=field_name)


def _normalize_id_list(
    value: list[int] | None,
    *,
    field_name: str,
    allow_empty: bool = False,
) -> list[int] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"{field_name} 必须为数组")
    normalized: list[int] = []
    seen: set[int] = set()
    for item in value:
        resolved = _normalize_positive_int(item, field_name=field_name)
        if resolved in seen:
            continue
        seen.add(resolved)
        normalized.append(resolved)
    if normalized:
        return normalized
    return [] if allow_empty else None


def _normalize_page(value: int, *, field_name: str) -> int:
    return _normalize_positive_int(value, field_name=field_name)


def _normalize_page_size(value: int) -> int:
    normalized = _normalize_positive_int(value, field_name="size")
    if normalized > CHAT_MAX_PAGE_SIZE:
        raise ValueError(f"size 不能超过 {CHAT_MAX_PAGE_SIZE}")
    return normalized


def _normalize_operation_window(
    start_at: datetime | None,
    end_at: datetime | None,
) -> tuple[datetime, datetime]:
    normalized_end = ensure_timezone(end_at) if end_at is not None else now_local()
    normalized_start = (
        ensure_timezone(start_at)
        if start_at is not None
        else normalized_end - timedelta(days=CHAT_OPERATION_DEFAULT_WINDOW_DAYS)
    )
    if normalized_start >= normalized_end:
        raise ValueError("start_at 必须早于 end_at")
    if normalized_end - normalized_start > timedelta(days=CHAT_OPERATION_MAX_WINDOW_DAYS):
        raise ValueError(f"统计时间范围不能超过 {CHAT_OPERATION_MAX_WINDOW_DAYS} 天")
    return normalized_start, normalized_end


def _normalize_recent_error_limit(value: int) -> int:
    normalized = _normalize_positive_int(value, field_name="recent_error_limit")
    if normalized > CHAT_OPERATION_MAX_RECENT_ERROR_LIMIT:
        raise ValueError(f"recent_error_limit 不能超过 {CHAT_OPERATION_MAX_RECENT_ERROR_LIMIT}")
    return normalized


def _normalize_optional_top_k(value: int | None) -> int | None:
    normalized = _normalize_optional_positive_int(value, field_name="top_k")
    if normalized is not None and normalized > CHAT_MAX_TOP_K:
        raise ValueError(f"top_k 不能超过 {CHAT_MAX_TOP_K}")
    return normalized


def _normalize_top_k(value: int, *, field_name: str = "top_k") -> int:
    normalized = _normalize_positive_int(value, field_name=field_name)
    if normalized > CHAT_MAX_TOP_K:
        raise ValueError(f"{field_name} 不能超过 {CHAT_MAX_TOP_K}")
    return normalized


def _normalize_optional_score_threshold(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("score_threshold 必须为数字")
    normalized = float(value)
    if normalized < 0 or normalized > 1:
        raise ValueError("score_threshold 必须在 0 到 1 之间")
    return normalized


def _normalize_optional_temperature(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("temperature 必须为数字")
    normalized = float(value)
    if normalized < 0 or normalized > 2:
        raise ValueError("temperature 必须在 0 到 2 之间")
    return normalized


def _normalize_mapping(value: dict[str, Any] | None, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} 必须为对象")
    return dict(value)


def _normalize_optional_run_mode(value: str | None) -> str | None:
    normalized = _normalize_optional_str(value, field_name="run_mode", max_length=32)
    if normalized is None:
        return None
    allowed = {
        CHAT_RUN_MODE_LLM_CHAT,
        CHAT_RUN_MODE_KNOWLEDGE_RAG,
        CHAT_RUN_MODE_FILE_CHAT,
        CHAT_RUN_MODE_AUTO,
    }
    if normalized not in allowed:
        raise ValueError("run_mode 不支持")
    return normalized


def _normalize_permissions(value: list[str]) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("permissions 必须为数组")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("permissions 必须为字符串数组")
        permission = item.strip()
        if not permission or permission in seen:
            continue
        seen.add(permission)
        normalized.append(permission)
    return normalized


def _normalize_bool(value: bool, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} 必须为布尔值")
    return value


def _normalize_config_source(value: str | None) -> str:
    normalized = (value or "draft").strip()
    if normalized not in {"draft", "published", "version"}:
        raise ValueError("config_source 仅支持 draft、published 或 version")
    return normalized


def _normalize_feedback_rating(value: str) -> str:
    normalized = _normalize_required_str(value, field_name="rating", max_length=16)
    if normalized not in {CHAT_FEEDBACK_RATING_LIKE, CHAT_FEEDBACK_RATING_DISLIKE}:
        raise ValueError("rating 仅支持 like 或 dislike")
    return normalized


def _normalize_feedback_status(value: str | None) -> str | None:
    normalized = _normalize_optional_str(value, field_name="status", max_length=32)
    if normalized is None:
        return None
    allowed = {
        CHAT_FEEDBACK_STATUS_OPEN,
        CHAT_FEEDBACK_STATUS_REVIEWED,
        CHAT_FEEDBACK_STATUS_RESOLVED,
        CHAT_FEEDBACK_STATUS_IGNORED,
    }
    if normalized not in allowed:
        raise ValueError("status 不支持")
    return normalized


def _normalize_feedback_type_code(value: str, *, field_name: str = "type_code") -> str:
    normalized = _normalize_required_str(
        value,
        field_name=field_name,
        max_length=CHAT_MAX_FEEDBACK_TYPE_CODE_LENGTH,
    )
    if not normalized.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"{field_name} 仅支持字母、数字、下划线或连字符")
    return normalized


def _normalize_feedback_type_codes(value: list[str] | None) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("type_codes 必须为数组")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        code = _normalize_feedback_type_code(item, field_name="type_codes")
        if code in seen:
            continue
        seen.add(code)
        normalized.append(code)
    return normalized


def _normalize_feedback_tags(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("eval_tags 必须为数组")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        tag = _normalize_required_str(item, field_name="eval_tags", max_length=64)
        if tag in seen:
            continue
        seen.add(tag)
        normalized.append(tag)
    return normalized


def _normalize_retrieval_config(
    *,
    retrieval_strategy: str | None,
    retrieval_config: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    raw_config = dict(retrieval_config or {})
    config = RetrievalConfig.from_sources(raw_config, strategy=retrieval_strategy or "HYBRID_RRF")
    return config.strategy, raw_config


@dataclass(slots=True)
class ChatAppListParams:
    keyword: str | None = None
    is_enabled: bool | None = None
    page: int = 1
    size: int = CHAT_DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        self.keyword = _normalize_optional_str(
            self.keyword,
            field_name="keyword",
            max_length=CHAT_MAX_TITLE_LENGTH,
        )
        if self.is_enabled is not None:
            self.is_enabled = _normalize_bool(self.is_enabled, field_name="is_enabled")
        self.page = _normalize_page(self.page, field_name="page")
        self.size = _normalize_page_size(self.size)


@dataclass(slots=True)
class ChatAppOperationMetricsListParams:
    keyword: str | None = None
    is_enabled: bool | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    page: int = 1
    size: int = CHAT_DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        self.keyword = _normalize_optional_str(
            self.keyword,
            field_name="keyword",
            max_length=CHAT_MAX_TITLE_LENGTH,
        )
        if self.is_enabled is not None:
            self.is_enabled = _normalize_bool(self.is_enabled, field_name="is_enabled")
        self.start_at, self.end_at = _normalize_operation_window(self.start_at, self.end_at)
        self.page = _normalize_page(self.page, field_name="page")
        self.size = _normalize_page_size(self.size)


@dataclass(slots=True)
class ChatAppOperationMetricsDetailParams:
    chat_app_id: int
    start_at: datetime | None = None
    end_at: datetime | None = None
    recent_error_limit: int = CHAT_OPERATION_DEFAULT_RECENT_ERROR_LIMIT

    def __post_init__(self) -> None:
        self.chat_app_id = _normalize_positive_int(self.chat_app_id, field_name="chat_app_id")
        self.start_at, self.end_at = _normalize_operation_window(self.start_at, self.end_at)
        self.recent_error_limit = _normalize_recent_error_limit(self.recent_error_limit)


@dataclass(slots=True)
class ChatAppCreateInput:
    name: str
    run_mode: str = CHAT_RUN_MODE_AUTO
    description: str | None = None
    knowledge_ids: list[int] = field(default_factory=list)
    system_prompt: str | None = None
    completion_model: str | None = None
    temperature: float | None = None
    top_k: int = CHAT_DEFAULT_TOP_K
    score_threshold: float | None = None
    retrieval_strategy: str | None = "HYBRID_RRF"
    retrieval_config: dict[str, Any] = field(default_factory=dict)
    is_enabled: bool = True
    is_default: bool = False
    user_id: int | None = None

    def __post_init__(self) -> None:
        self.name = _normalize_required_str(
            self.name,
            field_name="name",
            max_length=CHAT_MAX_TITLE_LENGTH,
        )
        self.description = _normalize_optional_str(
            self.description,
            field_name="description",
            max_length=CHAT_MAX_APP_DESCRIPTION_LENGTH,
        )
        self.run_mode = _normalize_optional_run_mode(self.run_mode) or CHAT_RUN_MODE_AUTO
        self.knowledge_ids = (
            _normalize_id_list(
                self.knowledge_ids,
                field_name="knowledge_ids",
                allow_empty=True,
            )
            or []
        )
        self.system_prompt = _normalize_optional_str(
            self.system_prompt,
            field_name="system_prompt",
            max_length=CHAT_MAX_SYSTEM_PROMPT_LENGTH,
        )
        self.completion_model = _normalize_optional_str(
            self.completion_model,
            field_name="completion_model",
            max_length=CHAT_MAX_MODEL_LENGTH,
        )
        self.temperature = _normalize_optional_temperature(self.temperature)
        self.top_k = _normalize_top_k(self.top_k)
        self.score_threshold = _normalize_optional_score_threshold(self.score_threshold)
        self.retrieval_config = _normalize_mapping(
            self.retrieval_config,
            field_name="retrieval_config",
        )
        self.retrieval_strategy, self.retrieval_config = _normalize_retrieval_config(
            retrieval_strategy=self.retrieval_strategy,
            retrieval_config=self.retrieval_config,
        )
        self.is_enabled = _normalize_bool(self.is_enabled, field_name="is_enabled")
        self.is_default = _normalize_bool(self.is_default, field_name="is_default")
        self.user_id = _normalize_optional_positive_int(self.user_id, field_name="user_id")


@dataclass(slots=True)
class ChatAppUpdateInput:
    user_id: int
    name: str | None = None
    run_mode: str | None = None
    description: str | None = None
    knowledge_ids: list[int] | None = None
    system_prompt: str | None = None
    completion_model: str | None = None
    temperature: float | None = None
    top_k: int | None = None
    score_threshold: float | None = None
    retrieval_strategy: str | None = None
    retrieval_config: dict[str, Any] | None = None
    is_default: bool | None = None
    null_fields: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        if self.name is not None:
            self.name = _normalize_required_str(
                self.name,
                field_name="name",
                max_length=CHAT_MAX_TITLE_LENGTH,
            )
        self.description = _normalize_optional_str(
            self.description,
            field_name="description",
            max_length=CHAT_MAX_APP_DESCRIPTION_LENGTH,
        )
        self.run_mode = _normalize_optional_run_mode(self.run_mode)
        if self.knowledge_ids is not None:
            self.knowledge_ids = (
                _normalize_id_list(
                    self.knowledge_ids,
                    field_name="knowledge_ids",
                    allow_empty=True,
                )
                or []
            )
        self.system_prompt = _normalize_optional_str(
            self.system_prompt,
            field_name="system_prompt",
            max_length=CHAT_MAX_SYSTEM_PROMPT_LENGTH,
        )
        self.completion_model = _normalize_optional_str(
            self.completion_model,
            field_name="completion_model",
            max_length=CHAT_MAX_MODEL_LENGTH,
        )
        self.temperature = _normalize_optional_temperature(self.temperature)
        if self.top_k is not None:
            self.top_k = _normalize_top_k(self.top_k)
        self.score_threshold = _normalize_optional_score_threshold(self.score_threshold)
        if self.retrieval_config is not None:
            self.retrieval_config = _normalize_mapping(
                self.retrieval_config,
                field_name="retrieval_config",
            )
        if self.retrieval_strategy is not None or self.retrieval_config is not None:
            normalized_strategy, normalized_config = _normalize_retrieval_config(
                retrieval_strategy=self.retrieval_strategy,
                retrieval_config=self.retrieval_config or {},
            )
            self.retrieval_strategy = (
                normalized_strategy if self.retrieval_strategy is not None else None
            )
            self.retrieval_config = normalized_config
        if self.is_default is not None:
            self.is_default = _normalize_bool(self.is_default, field_name="is_default")
        self.null_fields = set(self.null_fields)


@dataclass(slots=True)
class ChatAppPublishInput:
    user_id: int
    version_name: str | None = None
    publish_remark: str | None = None

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        self.version_name = _normalize_optional_str(
            self.version_name,
            field_name="version_name",
            max_length=CHAT_MAX_TITLE_LENGTH,
        )
        self.publish_remark = _normalize_optional_str(
            self.publish_remark,
            field_name="publish_remark",
            max_length=CHAT_MAX_APP_DESCRIPTION_LENGTH,
        )


@dataclass(slots=True)
class ChatAppRollbackInput(ChatAppPublishInput):
    pass


@dataclass(slots=True)
class ChatAppShareCreateInput:
    user_id: int
    expires_at: datetime | None = None
    daily_limit: int | None = None
    rate_limit: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        self.daily_limit = _normalize_optional_positive_int(
            self.daily_limit,
            field_name="daily_limit",
        )
        self.rate_limit = _normalize_mapping(self.rate_limit, field_name="rate_limit")


@dataclass(slots=True)
class ChatAppShareUpdateInput:
    user_id: int
    enabled: bool | None = None
    expires_at: datetime | None = None
    daily_limit: int | None = None
    rate_limit: dict[str, Any] | None = None
    null_fields: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        if self.enabled is not None:
            self.enabled = _normalize_bool(self.enabled, field_name="enabled")
        self.daily_limit = _normalize_optional_positive_int(
            self.daily_limit,
            field_name="daily_limit",
        )
        if self.rate_limit is not None:
            self.rate_limit = _normalize_mapping(self.rate_limit, field_name="rate_limit")


@dataclass(slots=True)
class ChatRunContext:
    knowledge_ids: list[int] | None = None
    file_ids: list[int] | None = None

    def __post_init__(self) -> None:
        self.knowledge_ids = _normalize_id_list(self.knowledge_ids, field_name="knowledge_ids")
        self.file_ids = _normalize_id_list(
            self.file_ids,
            field_name="file_ids",
            allow_empty=True,
        )


@dataclass(slots=True)
class ChatRunOptions:
    top_k: int | None = None
    retrieval_strategy: str | None = None
    retrieval_config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.top_k = _normalize_optional_top_k(self.top_k)
        if self.retrieval_config or self.retrieval_strategy is not None:
            original_config = dict(self.retrieval_config or {})
            config = RetrievalConfig.from_sources(
                original_config,
                strategy=self.retrieval_strategy,
            )
            self.retrieval_strategy = (
                config.strategy if self.retrieval_strategy is not None else None
            )
            self.retrieval_config = original_config


@dataclass(slots=True)
class ChatRunInput:
    user_id: int
    message: str
    chat_app_id: int | None = None
    session_id: int | None = None
    project_id: int | None = None
    project_name: str | None = None
    run_mode: str | None = None
    context: ChatRunContext = field(default_factory=ChatRunContext)
    options: ChatRunOptions = field(default_factory=ChatRunOptions)
    permissions: list[str] = field(default_factory=list)
    is_super_admin: bool = False

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        self.message = _normalize_required_str(
            self.message,
            field_name="message",
            max_length=CHAT_MAX_MESSAGE_LENGTH,
        )
        self.chat_app_id = _normalize_optional_positive_int(
            self.chat_app_id,
            field_name="chat_app_id",
        )
        self.session_id = _normalize_optional_positive_int(
            self.session_id,
            field_name="session_id",
        )
        self.project_id = _normalize_optional_positive_int(
            self.project_id,
            field_name="project_id",
        )
        self.project_name = _normalize_optional_str(
            self.project_name,
            field_name="project_name",
            max_length=CHAT_MAX_PROJECT_NAME_LENGTH,
        )
        self.run_mode = _normalize_optional_run_mode(self.run_mode)
        if not isinstance(self.context, ChatRunContext):
            raise ValueError("context 必须为 ChatRunContext")
        if not isinstance(self.options, ChatRunOptions):
            raise ValueError("options 必须为 ChatRunOptions")
        self.permissions = _normalize_permissions(self.permissions)
        self.is_super_admin = _normalize_bool(self.is_super_admin, field_name="is_super_admin")


@dataclass(slots=True)
class ChatPublicRunInput:
    share_token: str
    message: str
    visitor_session_token: str | None = None
    client_host: str | None = None
    user_id: int = 0
    chat_app_id: int | None = None
    project_id: int | None = None
    run_mode: str | None = None
    context: ChatRunContext = field(default_factory=ChatRunContext)
    options: ChatRunOptions = field(default_factory=ChatRunOptions)
    permissions: list[str] = field(default_factory=list)
    is_super_admin: bool = True

    def __post_init__(self) -> None:
        self.share_token = _normalize_required_str(
            self.share_token,
            field_name="share_token",
            max_length=256,
        )
        self.message = _normalize_required_str(
            self.message,
            field_name="message",
            max_length=CHAT_MAX_MESSAGE_LENGTH,
        )
        self.visitor_session_token = _normalize_optional_str(
            self.visitor_session_token,
            field_name="visitor_session_token",
            max_length=256,
        )
        self.client_host = _normalize_optional_str(
            self.client_host,
            field_name="client_host",
            max_length=128,
        )
        self.run_mode = _normalize_optional_run_mode(self.run_mode)
        self.context = self.context or ChatRunContext()
        self.options = self.options or ChatRunOptions()
        if not isinstance(self.context, ChatRunContext):
            raise ValueError("context 必须为 ChatRunContext")
        if not isinstance(self.options, ChatRunOptions):
            raise ValueError("options 必须为 ChatRunOptions")


@dataclass(slots=True)
class ChatDebugRunInput:
    user_id: int
    message: str
    config_source: str = "draft"
    version_id: int | None = None
    run_mode: str | None = None
    context: ChatRunContext = field(default_factory=ChatRunContext)
    options: ChatRunOptions = field(default_factory=ChatRunOptions)
    include_prompt: bool = True
    include_answer: bool = True
    permissions: list[str] = field(default_factory=list)
    is_super_admin: bool = False

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        self.message = _normalize_required_str(
            self.message,
            field_name="message",
            max_length=CHAT_MAX_MESSAGE_LENGTH,
        )
        self.config_source = _normalize_config_source(self.config_source)
        self.version_id = _normalize_optional_positive_int(self.version_id, field_name="version_id")
        if self.config_source == "version" and self.version_id is None:
            raise ValueError("config_source=version 时必须提供 version_id")
        self.run_mode = _normalize_optional_run_mode(self.run_mode)
        if not isinstance(self.context, ChatRunContext):
            raise ValueError("context 必须为 ChatRunContext")
        if not isinstance(self.options, ChatRunOptions):
            raise ValueError("options 必须为 ChatRunOptions")
        self.include_prompt = _normalize_bool(self.include_prompt, field_name="include_prompt")
        self.include_answer = _normalize_bool(self.include_answer, field_name="include_answer")
        self.permissions = _normalize_permissions(self.permissions)
        self.is_super_admin = _normalize_bool(self.is_super_admin, field_name="is_super_admin")


@dataclass(slots=True)
class ChatSessionListParams:
    user_id: int
    page: int = 1
    size: int = CHAT_DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        self.page = _normalize_page(self.page, field_name="page")
        self.size = _normalize_page_size(self.size)


@dataclass(slots=True)
class ChatProjectCreateInput:
    user_id: int
    name: str

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        self.name = _normalize_required_str(
            self.name,
            field_name="name",
            max_length=CHAT_MAX_PROJECT_NAME_LENGTH,
        )


@dataclass(slots=True)
class ChatProjectListParams:
    user_id: int

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")


@dataclass(slots=True)
class ChatDeleteProjectInput:
    user_id: int
    project_id: int

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        self.project_id = _normalize_positive_int(self.project_id, field_name="project_id")


@dataclass(slots=True)
class ChatMoveSessionProjectInput:
    user_id: int
    session_id: int
    project_id: int | None

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        self.session_id = _normalize_positive_int(self.session_id, field_name="session_id")
        self.project_id = _normalize_optional_positive_int(
            self.project_id,
            field_name="project_id",
        )


@dataclass(slots=True)
class ChatMessageListParams:
    user_id: int
    session_id: int
    page: int = 1
    size: int = CHAT_DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        self.session_id = _normalize_positive_int(self.session_id, field_name="session_id")
        self.page = _normalize_page(self.page, field_name="page")
        self.size = _normalize_page_size(self.size)


@dataclass(slots=True)
class ChatFeedbackTypeCreateInput:
    user_id: int
    type_code: str
    label: str
    description: str | None = None
    enabled: bool = True
    sort_order: int = 0
    requires_comment: bool = False
    handler_key: str = "noop"
    action_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        self.type_code = _normalize_feedback_type_code(self.type_code)
        self.label = _normalize_required_str(
            self.label,
            field_name="label",
            max_length=CHAT_MAX_FEEDBACK_TYPE_LABEL_LENGTH,
        )
        self.description = _normalize_optional_str(
            self.description,
            field_name="description",
            max_length=CHAT_MAX_FEEDBACK_TYPE_DESCRIPTION_LENGTH,
        )
        self.enabled = _normalize_bool(self.enabled, field_name="enabled")
        if isinstance(self.sort_order, bool) or not isinstance(self.sort_order, int):
            raise ValueError("sort_order 必须为整数")
        self.requires_comment = _normalize_bool(
            self.requires_comment,
            field_name="requires_comment",
        )
        self.handler_key = _normalize_required_str(
            self.handler_key,
            field_name="handler_key",
            max_length=CHAT_MAX_FEEDBACK_HANDLER_KEY_LENGTH,
        )
        self.action_schema = _normalize_mapping(self.action_schema, field_name="action_schema")
        self.metadata = _normalize_mapping(self.metadata, field_name="metadata")


@dataclass(slots=True)
class ChatFeedbackTypeUpdateInput:
    user_id: int
    label: str | None = None
    description: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None
    requires_comment: bool | None = None
    handler_key: str | None = None
    action_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    null_fields: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        if self.label is not None:
            self.label = _normalize_required_str(
                self.label,
                field_name="label",
                max_length=CHAT_MAX_FEEDBACK_TYPE_LABEL_LENGTH,
            )
        self.description = _normalize_optional_str(
            self.description,
            field_name="description",
            max_length=CHAT_MAX_FEEDBACK_TYPE_DESCRIPTION_LENGTH,
        )
        if self.enabled is not None:
            self.enabled = _normalize_bool(self.enabled, field_name="enabled")
        if self.sort_order is not None and (
            isinstance(self.sort_order, bool) or not isinstance(self.sort_order, int)
        ):
            raise ValueError("sort_order 必须为整数")
        if self.requires_comment is not None:
            self.requires_comment = _normalize_bool(
                self.requires_comment,
                field_name="requires_comment",
            )
        self.handler_key = _normalize_optional_str(
            self.handler_key,
            field_name="handler_key",
            max_length=CHAT_MAX_FEEDBACK_HANDLER_KEY_LENGTH,
        )
        if self.action_schema is not None:
            self.action_schema = _normalize_mapping(
                self.action_schema,
                field_name="action_schema",
            )
        if self.metadata is not None:
            self.metadata = _normalize_mapping(self.metadata, field_name="metadata")
        self.null_fields = set(self.null_fields)


@dataclass(slots=True)
class ChatMessageFeedbackInput:
    user_id: int
    message_id: int
    rating: str
    type_codes: list[str] = field(default_factory=list)
    comment: str | None = None

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        self.message_id = _normalize_positive_int(self.message_id, field_name="message_id")
        self.rating = _normalize_feedback_rating(self.rating)
        self.type_codes = _normalize_feedback_type_codes(self.type_codes)
        self.comment = _normalize_optional_str(
            self.comment,
            field_name="comment",
            max_length=CHAT_MAX_FEEDBACK_COMMENT_LENGTH,
        )
        if self.rating == CHAT_FEEDBACK_RATING_LIKE:
            self.type_codes = []
        if self.rating == CHAT_FEEDBACK_RATING_DISLIKE and not self.type_codes and not self.comment:
            raise ValueError("点踩反馈必须选择问题类型或填写备注")


@dataclass(slots=True)
class ChatMessageFeedbackQuery:
    user_id: int
    message_id: int

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        self.message_id = _normalize_positive_int(self.message_id, field_name="message_id")


@dataclass(slots=True)
class ChatFeedbackListParams:
    rating: str | None = None
    type_code: str | None = None
    status: str | None = None
    chat_app_id: int | None = None
    is_eval_candidate: bool | None = None
    keyword: str | None = None
    page: int = 1
    size: int = CHAT_DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        if self.rating is not None:
            self.rating = _normalize_feedback_rating(self.rating)
        if self.type_code is not None:
            self.type_code = _normalize_feedback_type_code(self.type_code)
        self.status = _normalize_feedback_status(self.status)
        self.chat_app_id = _normalize_optional_positive_int(
            self.chat_app_id,
            field_name="chat_app_id",
        )
        if self.is_eval_candidate is not None:
            self.is_eval_candidate = _normalize_bool(
                self.is_eval_candidate,
                field_name="is_eval_candidate",
            )
        self.keyword = _normalize_optional_str(
            self.keyword,
            field_name="keyword",
            max_length=CHAT_MAX_MESSAGE_LENGTH,
        )
        self.page = _normalize_page(self.page, field_name="page")
        self.size = _normalize_page_size(self.size)


@dataclass(slots=True)
class ChatFeedbackAdminUpdateInput:
    user_id: int
    status: str | None = None
    admin_note: str | None = None
    is_eval_candidate: bool | None = None
    eval_tags: list[str] | None = None
    eval_note: str | None = None
    null_fields: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        self.status = _normalize_feedback_status(self.status)
        self.admin_note = _normalize_optional_str(
            self.admin_note,
            field_name="admin_note",
            max_length=CHAT_MAX_FEEDBACK_ADMIN_NOTE_LENGTH,
        )
        if self.is_eval_candidate is not None:
            self.is_eval_candidate = _normalize_bool(
                self.is_eval_candidate,
                field_name="is_eval_candidate",
            )
        self.eval_tags = _normalize_feedback_tags(self.eval_tags)
        self.eval_note = _normalize_optional_str(
            self.eval_note,
            field_name="eval_note",
            max_length=CHAT_MAX_FEEDBACK_EVAL_NOTE_LENGTH,
        )
        self.null_fields = set(self.null_fields)


@dataclass(slots=True)
class ChatDeleteSessionInput:
    user_id: int
    session_id: int

    def __post_init__(self) -> None:
        self.user_id = _normalize_positive_int(self.user_id, field_name="user_id")
        self.session_id = _normalize_positive_int(self.session_id, field_name="session_id")


@dataclass(slots=True)
class ChatCitationRecord:
    file_id: int
    file_name: str | None
    chunk_id: int
    score: float
    content: str
    reference_index: int = 0
    marker: str = ""
    page_label: str = "页码未知"
    page_numbers: list[int] = field(default_factory=list)
    positions: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class ChatAttachmentRecord:
    file_id: int
    file_name: str
    file_size: int
    file_extension: str
    is_temporary: bool
    expires_at: datetime | None = None
    content_hash: str | None = None


@dataclass(slots=True)
class ChatEvidenceRecord(ChatCitationRecord):
    metadata_json: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChatStreamEvent:
    event: str
    session_id: int | None = None
    message_id: int | None = None
    visitor_session_token: str | None = None
    answer: str | None = None
    delta: str | None = None
    run_mode: str | None = None
    file_ids: list[int] = field(default_factory=list)
    citations: list[ChatCitationRecord] = field(default_factory=list)
    status: str | None = None
    error: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChatSessionRecord:
    id: int
    chat_app_id: int
    title: str
    user_id: int
    project_id: int | None
    project_name: str | None
    last_message_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(slots=True)
class ChatAppRecord:
    id: int
    name: str
    description: str | None
    run_mode: str
    knowledge_ids: list[int]
    system_prompt: str | None
    completion_model: str | None
    temperature: float | None
    top_k: int
    score_threshold: float | None
    retrieval_strategy: str
    retrieval_config: dict[str, Any]
    is_enabled: bool
    is_default: bool
    created_at: datetime | None
    updated_at: datetime | None
    created_by: int | None
    updated_by: int | None
    draft_updated_at: datetime | None = None
    published_version_id: int | None = None
    published_version_no: int | None = None
    published_at: datetime | None = None
    publish_status: str = "unpublished"
    has_unpublished_changes: bool = False


@dataclass(slots=True)
class ChatAppVersionRecord:
    id: int
    chat_app_id: int
    version_no: int
    version_name: str | None
    publish_remark: str | None
    config: dict[str, Any]
    is_current: bool
    published_at: datetime | None
    published_by: int | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(slots=True)
class ChatAppShareRecord:
    id: int
    chat_app_id: int
    version_id: int
    version_no: int
    enabled: bool
    expires_at: datetime | None
    daily_limit: int | None
    used_count_today: int
    used_date: str | None
    last_used_at: datetime | None
    rate_limit: dict[str, Any]
    created_at: datetime | None
    updated_at: datetime | None
    created_by: int | None
    updated_by: int | None
    share_token: str | None = None


@dataclass(slots=True)
class ChatAppOperationMetricRecord:
    chat_app_id: int
    chat_app_name: str
    is_enabled: bool
    publish_status: str
    total_calls: int
    success_calls: int
    failed_calls: int
    failure_rate: float
    avg_duration_ms: int | None
    public_share_calls: int


@dataclass(slots=True)
class ChatAppOperationErrorRecord:
    message_id: int
    session_id: int
    share_id: int | None
    source: str
    run_mode: str | None
    status_code: int | None
    code: int | None
    message: str | None
    duration_ms: int | None
    request_id: str | None
    trace_id: str | None
    created_at: datetime | None


@dataclass(slots=True)
class ChatAppOperationMetricDetailRecord(ChatAppOperationMetricRecord):
    recent_errors: list[ChatAppOperationErrorRecord] = field(default_factory=list)


@dataclass(slots=True)
class ChatPublicShareRecord:
    chat_app_name: str
    description: str | None
    run_mode: str
    version_no: int
    expires_at: datetime | None


@dataclass(slots=True)
class ChatAppRuntimeConfig:
    id: int
    run_mode: str
    knowledge_ids_json: list[int]
    system_prompt: str | None
    completion_model: str | None
    temperature: float | None
    top_k: int
    score_threshold: float | None
    retrieval_strategy: str
    retrieval_config_json: dict[str, Any]
    version_id: int | None = None
    version_no: int | None = None
    config_source: str = "published"


@dataclass(slots=True)
class ChatDebugRunRecord:
    chat_app_id: int
    config_source: str
    version_id: int | None
    run_mode: str
    resolved_config: dict[str, Any]
    messages: list[dict[str, Any]]
    memory: dict[str, Any]
    retrieval: dict[str, Any]
    citations: list[ChatCitationRecord]
    answer: str | None
    timings: dict[str, int]
    error: dict[str, Any]


@dataclass(slots=True)
class ChatProjectRecord:
    id: int
    name: str
    user_id: int
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(slots=True)
class ChatFeedbackTypeRecord:
    id: int
    type_code: str
    label: str
    description: str | None
    enabled: bool
    sort_order: int
    requires_comment: bool
    handler_key: str
    action_schema: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime | None
    updated_at: datetime | None
    created_by: int | None
    updated_by: int | None


@dataclass(slots=True)
class ChatFeedbackHandlerRecord:
    key: str
    label: str
    description: str


@dataclass(slots=True)
class ChatMessageFeedbackRecord:
    id: int
    message_id: int
    session_id: int
    chat_app_id: int
    chat_app_version_id: int | None
    chat_app_version_no: int | None
    user_id: int
    rating: str
    type_codes: list[str]
    comment: str | None
    status: str
    is_eval_candidate: bool
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(slots=True)
class ChatFeedbackRecord(ChatMessageFeedbackRecord):
    admin_note: str | None
    handler_results: dict[str, Any]
    eval_tags: list[str]
    eval_note: str | None
    reviewed_by: int | None
    reviewed_at: datetime | None
    question_message_id: int | None
    question_content: str | None
    answer_content: str
    citations: list[dict[str, Any]]
    evidences: list[dict[str, Any]]
    run_mode: str | None
    trace_id: str | None
    request_id: str | None
    generation_name: str | None
    observability_provider: str | None
    observability_env: str | None
    metadata: dict[str, Any]
    created_by: int | None
    updated_by: int | None


@dataclass(slots=True)
class ChatMessageRecord:
    id: int
    session_id: int
    role: str
    content: str
    status: str
    run_mode: str | None
    trace_id: str | None
    request_id: str | None
    generation_name: str | None
    observability_provider: str | None
    observability_env: str | None
    knowledge_ids: list[int]
    file_ids: list[int]
    attachments: list[ChatAttachmentRecord]
    citations: list[ChatCitationRecord]
    error: dict[str, Any]
    feedback: ChatMessageFeedbackRecord | None
    created_at: datetime | None
    updated_at: datetime | None


def build_session_title(message: str) -> str:
    """根据首条消息生成会话标题。"""

    normalized = _normalize_required_str(
        message,
        field_name="message",
        max_length=CHAT_MAX_MESSAGE_LENGTH,
    )
    return normalized[:CHAT_MAX_TITLE_LENGTH]


__all__ = [
    "ChatAppCreateInput",
    "ChatAppListParams",
    "ChatAppOperationErrorRecord",
    "ChatAppOperationMetricDetailRecord",
    "ChatAppOperationMetricRecord",
    "ChatAppOperationMetricsDetailParams",
    "ChatAppOperationMetricsListParams",
    "ChatAppPublishInput",
    "ChatAppRecord",
    "ChatAppRollbackInput",
    "ChatAppRuntimeConfig",
    "ChatAppShareCreateInput",
    "ChatAppShareRecord",
    "ChatAppShareUpdateInput",
    "ChatAppUpdateInput",
    "ChatAppVersionRecord",
    "ChatDebugRunInput",
    "ChatDebugRunRecord",
    "ChatCitationRecord",
    "ChatAttachmentRecord",
    "ChatDeleteProjectInput",
    "ChatDeleteSessionInput",
    "ChatEvidenceRecord",
    "ChatFeedbackAdminUpdateInput",
    "ChatFeedbackHandlerRecord",
    "ChatFeedbackListParams",
    "ChatFeedbackRating",
    "ChatFeedbackRecord",
    "ChatFeedbackStatus",
    "ChatFeedbackTypeCreateInput",
    "ChatFeedbackTypeRecord",
    "ChatFeedbackTypeUpdateInput",
    "ChatMoveSessionProjectInput",
    "ChatMessageFeedbackInput",
    "ChatMessageFeedbackQuery",
    "ChatMessageFeedbackRecord",
    "ChatMessageListParams",
    "ChatMessageRecord",
    "ChatMessageRole",
    "ChatMessageStatus",
    "ChatProjectCreateInput",
    "ChatProjectListParams",
    "ChatProjectRecord",
    "ChatPublicRunInput",
    "ChatPublicShareRecord",
    "ChatRunContext",
    "ChatRunInput",
    "ChatRunMode",
    "ChatRunOptions",
    "ChatSessionListParams",
    "ChatSessionRecord",
    "ChatStreamEvent",
    "ChatStreamEventType",
    "build_session_title",
]
