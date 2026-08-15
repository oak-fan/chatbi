"""ChatBI 业务知识接口 Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from cogmait_shared.api import SnowflakeID
from cogmait_shared.core.datetime_utils import serialize_datetime

from ....constants.chatbi.query import CHATBI_PAGE_DEFAULT_SIZE


class _ChatbiBizKnSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True, extra="forbid")


class _ChatbiBizKnRequestSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=False, from_attributes=True, extra="forbid")


class ChatbiBusinessKnowledgeCreateRequest(_ChatbiBizKnRequestSchema):
    content: str
    scope: str
    kind: str
    datasource_id: SnowflakeID = Field(alias="datasourceId")


class ChatbiBusinessKnowledgeUpdateRequest(_ChatbiBizKnRequestSchema):
    content: str | None = None
    scope: str | None = None
    kind: str | None = None
    datasource_id: SnowflakeID | None = Field(default=None, alias="datasourceId")


class ChatbiBusinessKnowledgeListQuery(_ChatbiBizKnRequestSchema):
    page: int = 1
    page_size: int = Field(default=CHATBI_PAGE_DEFAULT_SIZE, alias="pageSize")
    scope: str | None = None
    kind: str | None = None
    datasource_id: SnowflakeID | None = Field(default=None, alias="datasourceId")


class ChatbiBusinessKnowledgeRecordOut(_ChatbiBizKnSchema):
    id: SnowflakeID
    content: str
    scope: str
    kind: str
    datasource_id: SnowflakeID = Field(alias="datasourceId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @field_serializer("created_at", "updated_at")
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return serialize_datetime(value)


class ChatbiBusinessKnowledgeListResponse(_ChatbiBizKnSchema):
    total: int
    current: int
    page_size: int = Field(alias="pageSize")
    records: list[ChatbiBusinessKnowledgeRecordOut]
