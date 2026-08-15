"""Chat ORM 模型。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from cogmait_shared.core.id_generator import generate_snowflake_id
from cogmait_shared.db import AuditSoftDeleteMixin, Base

from ...constants.chat import (
    CHAT_DEFAULT_APP_NAME,
    CHAT_DEFAULT_TOP_K,
    CHAT_FEEDBACK_HANDLER_NOOP,
    CHAT_FEEDBACK_STATUS_OPEN,
    CHAT_FILE_PARSE_MODE_NORMAL,
    CHAT_FILE_PARSE_STATUS_PENDING,
    CHAT_MAX_APP_DESCRIPTION_LENGTH,
    CHAT_MAX_FEEDBACK_ADMIN_NOTE_LENGTH,
    CHAT_MAX_FEEDBACK_COMMENT_LENGTH,
    CHAT_MAX_FEEDBACK_EVAL_NOTE_LENGTH,
    CHAT_MAX_FEEDBACK_HANDLER_KEY_LENGTH,
    CHAT_MAX_FEEDBACK_TYPE_CODE_LENGTH,
    CHAT_MAX_FEEDBACK_TYPE_DESCRIPTION_LENGTH,
    CHAT_MAX_FEEDBACK_TYPE_LABEL_LENGTH,
    CHAT_MAX_MODEL_LENGTH,
    CHAT_MAX_PROJECT_NAME_LENGTH,
    CHAT_MAX_TITLE_LENGTH,
    CHAT_MESSAGE_STATUS_SUCCESS,
    CHAT_RUN_MODE_AUTO,
    CHAT_SESSION_SOURCE_CHAT,
)

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class ChatApp(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chat_app"
    __table_args__ = (
        Index(
            "uq_ais_chat_app_name_active",
            "name",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        Index(
            "uq_ais_chat_app_default_active",
            "is_default",
            unique=True,
            postgresql_where=text("is_default = true AND is_deleted = false"),
            sqlite_where=text("is_default = 1 AND is_deleted = 0"),
        ),
        Index("idx_ais_chat_app_enabled_deleted", "is_enabled", "is_deleted", "id"),
        {"comment": "Chat 应用配置表"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="Chat 应用 ID",
    )
    name: Mapped[str] = mapped_column(
        String(CHAT_MAX_TITLE_LENGTH),
        nullable=False,
        default=CHAT_DEFAULT_APP_NAME,
        comment="Chat 应用名称",
    )
    description: Mapped[str | None] = mapped_column(
        String(CHAT_MAX_APP_DESCRIPTION_LENGTH),
        nullable=True,
        comment="Chat 应用描述",
    )
    run_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CHAT_RUN_MODE_AUTO,
        comment="运行模式",
    )
    knowledge_ids_json: Mapped[list[int]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=list,
        comment="默认关联知识库 ID 列表",
    )
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True, comment="系统提示词")
    completion_model: Mapped[str | None] = mapped_column(
        String(CHAT_MAX_MODEL_LENGTH),
        nullable=True,
        comment="默认对话模型",
    )
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True, comment="生成温度")
    top_k: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=CHAT_DEFAULT_TOP_K,
        comment="RAG 检索数量",
    )
    score_threshold: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        comment="RAG 命中阈值",
    )
    retrieval_strategy: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="HYBRID_RRF",
        comment="RAG 检索策略",
    )
    retrieval_config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
        comment="RAG 检索策略参数",
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="是否启用",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否默认 Chat 应用",
    )
    published_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="当前发布版本 ID",
    )
    published_version_no: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="当前发布版本号",
    )
    published_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="当前发布时间",
    )
    draft_updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="草稿最近更新时间",
    )


class ChatAppVersion(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chat_app_version"
    __table_args__ = (
        Index(
            "uq_ais_chat_app_version_no_active",
            "chat_app_id",
            "version_no",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        Index(
            "uq_ais_chat_app_version_current_active",
            "chat_app_id",
            "is_current",
            unique=True,
            postgresql_where=text("is_current = true AND is_deleted = false"),
            sqlite_where=text("is_current = 1 AND is_deleted = 0"),
        ),
        Index(
            "idx_ais_chat_app_version_app_deleted_no",
            "chat_app_id",
            "is_deleted",
            "version_no",
        ),
        {"comment": "Chat 应用发布版本表"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="Chat 应用发布版本 ID",
    )
    chat_app_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Chat 应用 ID")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    version_name: Mapped[str | None] = mapped_column(
        String(CHAT_MAX_TITLE_LENGTH),
        nullable=True,
        comment="版本名称",
    )
    publish_remark: Mapped[str | None] = mapped_column(
        String(CHAT_MAX_APP_DESCRIPTION_LENGTH),
        nullable=True,
        comment="发布备注",
    )
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
        comment="发布运行配置快照",
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否当前发布版本",
    )
    published_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="发布时间",
    )
    published_by: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="发布人",
    )


class ChatAppShare(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chat_app_share"
    __table_args__ = (
        Index(
            "uq_ais_chat_app_share_token_active",
            "share_token_hash",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        Index(
            "idx_ais_chat_app_share_app_deleted_created",
            "chat_app_id",
            "is_deleted",
            "created_at",
            "id",
        ),
        Index("idx_ais_chat_app_share_version", "version_id", "is_deleted", "id"),
        {"comment": "ChatApp 免登陆分享表"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="ChatApp 分享 ID",
    )
    chat_app_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="ChatApp ID")
    version_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="绑定发布版本 ID")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="绑定发布版本号")
    share_token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="分享 token 哈希",
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用")
    expires_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="过期时间",
    )
    daily_limit: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="每日调用上限",
    )
    used_count_today: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="当日调用次数",
    )
    used_date: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="计数日期")
    last_used_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近调用时间",
    )
    rate_limit_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
        comment="短窗口限流配置",
    )


class ChatSession(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chat_session"
    __table_args__ = (
        Index(
            "idx_ais_chat_session_user_deleted_updated",
            "user_id",
            "is_deleted",
            "last_message_at",
            "id",
        ),
        Index("idx_ais_chat_session_app_deleted", "chat_app_id", "is_deleted", "id"),
        Index("idx_ais_chat_session_user_project", "user_id", "project_id", "is_deleted", "id"),
        Index(
            "idx_ais_chat_session_share_visitor",
            "share_id",
            "visitor_id_hash",
            "is_deleted",
            "id",
        ),
        Index(
            "idx_ais_chat_session_source_deleted",
            "source",
            "is_deleted",
            "last_message_at",
            "id",
        ),
        {"comment": "Chat 会话表"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="会话 ID",
    )
    chat_app_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Chat 应用 ID")
    title: Mapped[str] = mapped_column(
        String(CHAT_MAX_TITLE_LENGTH),
        nullable=False,
        comment="会话标题",
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="用户 ID")
    share_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="公开分享 ID",
    )
    visitor_id_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="访客会话 token 哈希",
    )
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CHAT_SESSION_SOURCE_CHAT,
        comment="会话来源",
    )
    project_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="项目 ID",
    )
    project_name: Mapped[str | None] = mapped_column(
        String(CHAT_MAX_PROJECT_NAME_LENGTH),
        nullable=True,
        comment="项目名称",
    )
    last_message_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近消息时间",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
        comment="扩展信息",
    )


class ChatProject(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chat_project"
    __table_args__ = (
        Index("idx_ais_chat_project_user_deleted", "user_id", "is_deleted", "created_at", "id"),
        {"comment": "Chat 项目表"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="项目 ID",
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="用户 ID")
    name: Mapped[str] = mapped_column(
        String(CHAT_MAX_PROJECT_NAME_LENGTH),
        nullable=False,
        comment="项目名称",
    )


class ChatMessage(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chat_message"
    __table_args__ = (
        Index(
            "idx_ais_chat_message_session_deleted_created",
            "session_id",
            "is_deleted",
            "created_at",
            "id",
        ),
        Index(
            "idx_ais_chat_message_ops_role_created",
            "role",
            "is_deleted",
            "created_at",
            "status",
            "id",
        ),
        Index(
            "idx_ais_chat_message_ops_session_created",
            "session_id",
            "role",
            "is_deleted",
            "created_at",
            "id",
        ),
        {"comment": "Chat 消息表"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="消息 ID",
    )
    session_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="会话 ID")
    role: Mapped[str] = mapped_column(String(32), nullable=False, comment="消息角色")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息内容")
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CHAT_MESSAGE_STATUS_SUCCESS,
        comment="消息状态",
    )
    run_mode: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="运行模式")
    trace_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="观测 Trace ID",
    )
    request_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="观测请求 ID",
    )
    generation_name: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="Langfuse generation 名称",
    )
    observability_provider: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="观测 Provider",
    )
    observability_env: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="观测环境",
    )
    knowledge_ids_json: Mapped[list[int]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=list,
        comment="本次使用的知识库 ID 列表",
    )
    file_ids_json: Mapped[list[int]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=list,
        comment="本次使用的临时文件 ID 列表",
    )
    attachments_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=list,
        comment="本次使用的临时文件快照",
    )
    evidences_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=list,
        comment="RAG 检索命中片段",
    )
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=list,
        comment="返回引用来源",
    )
    usage_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
        comment="模型用量统计",
    )
    error_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
        comment="失败原因",
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="本次调用总耗时毫秒",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
        comment="消息扩展信息",
    )


class ChatFeedbackType(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chat_feedback_type"
    __table_args__ = (
        Index(
            "uq_ais_chat_feedback_type_code_active",
            "type_code",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        Index(
            "idx_ais_chat_feedback_type_enabled_sort",
            "enabled",
            "is_deleted",
            "sort_order",
            "id",
        ),
        {"comment": "Chat 反馈类型表"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="反馈类型 ID",
    )
    type_code: Mapped[str] = mapped_column(
        String(CHAT_MAX_FEEDBACK_TYPE_CODE_LENGTH),
        nullable=False,
        comment="类型编码",
    )
    label: Mapped[str] = mapped_column(
        String(CHAT_MAX_FEEDBACK_TYPE_LABEL_LENGTH),
        nullable=False,
        comment="展示文案",
    )
    description: Mapped[str | None] = mapped_column(
        String(CHAT_MAX_FEEDBACK_TYPE_DESCRIPTION_LENGTH),
        nullable=True,
        comment="类型说明",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="是否启用",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="排序")
    requires_comment: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否要求备注",
    )
    handler_key: Mapped[str] = mapped_column(
        String(CHAT_MAX_FEEDBACK_HANDLER_KEY_LENGTH),
        nullable=False,
        default=CHAT_FEEDBACK_HANDLER_NOOP,
        comment="处理器键",
    )
    action_schema_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
        comment="操作配置",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
        comment="扩展信息",
    )


class ChatFeedback(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chat_feedback"
    __table_args__ = (
        Index(
            "uq_ais_chat_feedback_message_user_active",
            "message_id",
            "user_id",
            unique=True,
            postgresql_where=text("is_deleted = false"),
            sqlite_where=text("is_deleted = 0"),
        ),
        Index("idx_ais_chat_feedback_user_message", "user_id", "message_id", "is_deleted"),
        Index(
            "idx_ais_chat_feedback_status_rating_eval",
            "status",
            "rating",
            "is_eval_candidate",
            "created_at",
            "id",
        ),
        Index("idx_ais_chat_feedback_app_created", "chat_app_id", "created_at", "id"),
        {"comment": "Chat 反馈表"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="反馈 ID",
    )
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="助手消息 ID")
    session_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="会话 ID")
    chat_app_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="ChatApp ID")
    chat_app_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="ChatApp 发布版本 ID",
    )
    chat_app_version_no: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="ChatApp 发布版本号",
    )
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="反馈用户 ID")
    rating: Mapped[str] = mapped_column(String(16), nullable=False, comment="评分")
    type_codes_json: Mapped[list[str]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=list,
        comment="问题类型编码",
    )
    comment: Mapped[str | None] = mapped_column(
        String(CHAT_MAX_FEEDBACK_COMMENT_LENGTH),
        nullable=True,
        comment="用户备注",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CHAT_FEEDBACK_STATUS_OPEN,
        comment="处理状态",
    )
    admin_note: Mapped[str | None] = mapped_column(
        String(CHAT_MAX_FEEDBACK_ADMIN_NOTE_LENGTH),
        nullable=True,
        comment="管理员备注",
    )
    handler_results_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
        comment="处理器结果",
    )
    is_eval_candidate: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="评测候选",
    )
    eval_tags_json: Mapped[list[str]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=list,
        comment="评测标签",
    )
    eval_note: Mapped[str | None] = mapped_column(
        String(CHAT_MAX_FEEDBACK_EVAL_NOTE_LENGTH),
        nullable=True,
        comment="评测备注",
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="处理人",
    )
    reviewed_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="处理时间",
    )
    question_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="问题消息 ID",
    )
    question_content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="问题快照")
    answer_content: Mapped[str] = mapped_column(Text, nullable=False, comment="答案快照")
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=list,
        comment="引用快照",
    )
    evidences_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=list,
        comment="检索证据快照",
    )
    run_mode: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="运行模式")
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="Trace ID")
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="请求 ID")
    generation_name: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="生成名称",
    )
    observability_provider: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="观测 Provider",
    )
    observability_env: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="观测环境",
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
        comment="扩展信息",
    )


class ChatFileContext(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chat_file_context"
    __table_args__ = (
        Index(
            "idx_ais_chat_file_context_session_file",
            "session_id",
            "source_file_id",
            "is_deleted",
        ),
        Index(
            "idx_ais_chat_file_context_hash_user",
            "user_id",
            "content_hash",
            "parse_mode",
            "parse_status",
            "expires_at",
        ),
        {"comment": "Chat 临时文件上下文表"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="上下文 ID",
    )
    session_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="会话 ID")
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="用户 ID")
    source_file_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="源文件 ID")
    source_file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="源文件名")
    source_file_extension: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="源文件类型",
    )
    source_file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="源文件大小")
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="内容指纹")
    parse_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CHAT_FILE_PARSE_MODE_NORMAL,
        comment="解析模式",
    )
    parse_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CHAT_FILE_PARSE_STATUS_PENDING,
        comment="解析状态",
    )
    provider_used: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="解析器")
    extracted_file_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="解析 markdown 文件 ID",
    )
    extracted_expires_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="解析产物到期时间",
    )
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="切片数")
    expires_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="上下文到期时间",
    )
    error_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
        comment="解析失败原因",
    )


class ChatFileChunk(Base, AuditSoftDeleteMixin):
    __tablename__ = "ais_chat_file_chunk"
    __table_args__ = (
        Index(
            "idx_ais_chat_file_chunk_context_order",
            "context_id",
            "is_deleted",
            "chunk_index",
            "id",
        ),
        Index("idx_ais_chat_file_chunk_file_hash", "source_file_id", "content_hash"),
        {"comment": "Chat 临时文件切片表"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        default=generate_snowflake_id,
        autoincrement=False,
        comment="切片 ID",
    )
    context_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="上下文 ID")
    source_file_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="源文件 ID")
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="内容指纹")
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="文件内顺序")
    heading_path: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="标题路径")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="切片正文")
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="字符数")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE,
        nullable=False,
        default=dict,
        comment="扩展信息",
    )


__all__ = [
    "ChatApp",
    "ChatAppShare",
    "ChatAppVersion",
    "ChatFileChunk",
    "ChatFileContext",
    "ChatFeedback",
    "ChatFeedbackType",
    "ChatMessage",
    "ChatSession",
]
