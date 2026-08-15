"""ChatBI Q-SQL 接口 Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from cogmait_shared.api import SnowflakeID
from cogmait_shared.core.datetime_utils import serialize_datetime

from ....constants.chatbi.query import CHATBI_PAGE_DEFAULT_SIZE


class _ChatbiQsqlSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True, extra="forbid")


class _ChatbiQsqlRequestSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=False, from_attributes=True, extra="forbid")


class ChatbiQsqlCreateRequest(_ChatbiQsqlRequestSchema):
    datasource_id: SnowflakeID = Field(alias="datasourceId")
    question: str
    sql_body: str = Field(alias="sqlBody")


class ChatbiQsqlUpdateRequest(_ChatbiQsqlRequestSchema):
    question: str | None = None
    sql_body: str | None = Field(default=None, alias="sqlBody")


class ChatbiQsqlListQuery(_ChatbiQsqlRequestSchema):
    page: int = 1
    page_size: int = Field(default=CHATBI_PAGE_DEFAULT_SIZE, alias="pageSize")
    datasource_id: SnowflakeID | None = Field(default=None, alias="datasourceId")


class ChatbiQsqlRecordOut(_ChatbiQsqlSchema):
    id: SnowflakeID
    datasource_id: SnowflakeID = Field(alias="datasourceId")
    question: str
    sql_body: str = Field(alias="sqlBody")
    llm_simplified_description: str | None = Field(alias="llmSimplifiedDescription")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @field_serializer("created_at", "updated_at")
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return serialize_datetime(value)


class ChatbiQsqlListResponse(_ChatbiQsqlSchema):
    total: int
    current: int
    page_size: int = Field(alias="pageSize")
    records: list[ChatbiQsqlRecordOut]
