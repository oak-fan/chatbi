"""ChatBI 问数接口 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from cogmait_shared.api import SnowflakeID
from cogmait_shared.core.datetime_utils import serialize_datetime


class _ChatbiQuerySchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True, extra="forbid")


class _ChatbiQueryRequestSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=False, from_attributes=True, extra="forbid")


class ChatbiQueryStreamRequest(_ChatbiQueryRequestSchema):
    question: str
    datasource_id: SnowflakeID | None = Field(default=None, alias="datasourceId")
    session_id: SnowflakeID | None = Field(default=None, alias="sessionId")
    clarification_token: str | None = Field(default=None, alias="clarificationToken")
    clarification_skip: bool = Field(default=False, alias="clarificationSkip")
    sql_candidate_paths: list[str] = Field(alias="sqlCandidatePaths")
    sql_selection_enabled: bool | None = Field(default=None, alias="sqlSelectionEnabled")
    sql_validate_enabled: bool | None = Field(default=None, alias="sqlValidateEnabled")
    value_founding_enabled: bool | None = Field(default=None, alias="valueFoundingEnabled")
    value_search_enabled: bool | None = Field(default=None, alias="valueSearchEnabled")
    group_by_audit_enabled: bool | None = Field(default=None, alias="groupByAuditEnabled")
    rewrite_enabled: bool | None = Field(default=None, alias="rewriteEnabled")
    summary_enabled: bool | None = Field(default=None, alias="summaryEnabled")
    business_knowledge_recall_enabled: bool | None = Field(default=None, alias="businessKnowledgeRecallEnabled")
    schema_selection_enabled: bool | None = Field(default=None, alias="schemaSelectionEnabled")
    qsql_recall_enabled: bool | None = Field(default=None, alias="qsqlRecallEnabled")
    sql_fix_enabled: bool | None = Field(default=None, alias="sqlFixEnabled")
    rag_enabled: bool | None = Field(default=None, alias="ragEnabled")


class ChatbiQueryLogDetailOut(_ChatbiQuerySchema):
    id: SnowflakeID
    assistant_message_id: SnowflakeID = Field(alias="assistantMessageId")
    user_message_id: SnowflakeID | None = Field(alias="userMessageId")
    request_id: str | None = Field(alias="requestId")
    datasource_id: SnowflakeID | None = Field(alias="datasourceId")
    user_question: str = Field(alias="userQuestion")
    rewritten_question: str | None = Field(alias="rewrittenQuestion")
    intent: str | None = None
    final_sql: str | None = Field(alias="finalSql")
    result_preview: dict[str, Any] | list[Any] | None = Field(alias="resultPreview")
    latency_ms: int | None = Field(alias="latencyMs")
    meta: dict[str, Any]
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @field_serializer("created_at", "updated_at")
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return serialize_datetime(value)
