"""ChatBI 数据源接口 Schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from cogmait_shared.api import SnowflakeID
from cogmait_shared.core.datetime_utils import serialize_datetime

from ....constants.chatbi.query import CHATBI_PAGE_DEFAULT_SIZE


class _ChatbiSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True, extra="forbid")


class _ChatbiDatasourceRequestSchema(BaseModel):
    model_config = ConfigDict(populate_by_name=False, from_attributes=True, extra="forbid")


class ChatbiDatasourceCreateRequest(_ChatbiDatasourceRequestSchema):
    name: str
    connector_type: str = Field(alias="connectorType")
    host: str | None = None
    port: int | None = None
    database: str | None = Field(default=None, alias="database")
    schema_name: str | None = Field(default=None, alias="schemaName")
    username: str | None = None
    password: str | None = None
    extra_params: dict[str, Any] | None = Field(default=None, alias="extraParams")
    remark: str | None = None


class ChatbiDatasourceUpdateRequest(_ChatbiDatasourceRequestSchema):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = Field(default=None, alias="database")
    schema_name: str | None = Field(default=None, alias="schemaName")
    username: str | None = None
    password: str | None = None
    extra_params: dict[str, Any] | None = Field(default=None, alias="extraParams")
    remark: str | None = None


class ChatbiDatasourceFromFilesRequest(_ChatbiDatasourceRequestSchema):
    name: str
    file_ids: list[SnowflakeID] = Field(alias="fileIds")
    remark: str | None = None


class ChatbiDatasourceListQuery(_ChatbiDatasourceRequestSchema):
    page: int = 1
    page_size: int = Field(default=CHATBI_PAGE_DEFAULT_SIZE, alias="pageSize")
    name: str | None = None
    connector_type: str | None = Field(default=None, alias="connectorType")


class ChatbiDbSchemaForeignKeyRefOut(_ChatbiSchema):
    table: str
    column: str


class ChatbiDbSchemaForeignKeyOut(_ChatbiSchema):
    column: str
    references: ChatbiDbSchemaForeignKeyRefOut
    constraint_name: str = Field(default="", alias="constraintName")


class ChatbiDbSchemaColumnOut(_ChatbiSchema):
    name: str
    column_type: str = Field(alias="type")
    constraints: list[str] = Field(default_factory=list)
    comment: str = ""
    description: str = ""
    samples: list[str] = Field(default_factory=list)


class ChatbiDbSchemaTableOut(_ChatbiSchema):
    table_name: str = Field(alias="tableName")
    columns: list[ChatbiDbSchemaColumnOut]
    foreign_keys: list[ChatbiDbSchemaForeignKeyOut] = Field(
        default_factory=list,
        alias="foreignKeys",
    )


class ChatbiDbSchemaOut(_ChatbiSchema):
    database: str
    description: str = ""
    tables: list[ChatbiDbSchemaTableOut]


class ChatbiDatasourceRecordOut(_ChatbiSchema):
    id: SnowflakeID
    origin: str
    name: str
    connector_type: str = Field(alias="connectorType")
    host: str
    port: int
    database: str = Field(alias="database")
    schema_name: str | None = Field(alias="schemaName")
    username: str
    import_file_ids: list[SnowflakeID] | None = Field(alias="importFileIds")
    db_schema: ChatbiDbSchemaOut | None = Field(alias="dbSchema")
    db_schema_updated_at: datetime | None = Field(alias="dbSchemaUpdatedAt")
    extra_params: dict[str, Any] | None = Field(alias="extraParams")
    remark: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    @field_serializer("db_schema_updated_at", "created_at", "updated_at")
    def _serialize_datetime(self, value: datetime | None) -> str | None:
        return serialize_datetime(value)

    @field_serializer("import_file_ids")
    def _serialize_import_file_ids(self, value: list[int] | None) -> list[str] | None:
        if value is None:
            return None
        return [str(item) for item in value]


class ChatbiDatasourceListResponse(_ChatbiSchema):
    total: int
    current: int
    page_size: int = Field(alias="pageSize")
    records: list[ChatbiDatasourceRecordOut]


class ChatbiDatasourceExecuteSqlRequest(_ChatbiSchema):
    sql: str


class ChatbiDatasourceExecuteSqlRow(_ChatbiSchema):
    model_config = ConfigDict(populate_by_name=True, from_attributes=True, extra="allow")


class ChatbiDatasourceExecuteSqlResponse(_ChatbiSchema):
    columns: list[str]
    rows: list[dict[str, Any]]
    truncated: bool


class ChatbiDatasourcePreprocessResponse(_ChatbiSchema):
    task_id: SnowflakeID = Field(alias="taskId")


__all__ = [
    "ChatbiDatasourceCreateRequest",
    "ChatbiDatasourceExecuteSqlRequest",
    "ChatbiDatasourceExecuteSqlResponse",
    "ChatbiDatasourceFromFilesRequest",
    "ChatbiDatasourceListQuery",
    "ChatbiDatasourceListResponse",
    "ChatbiDatasourcePreprocessResponse",
    "ChatbiDatasourceRecordOut",
    "ChatbiDatasourceUpdateRequest",
    "ChatbiDbSchemaColumnOut",
    "ChatbiDbSchemaForeignKeyOut",
    "ChatbiDbSchemaForeignKeyRefOut",
    "ChatbiDbSchemaOut",
    "ChatbiDbSchemaTableOut",
]
