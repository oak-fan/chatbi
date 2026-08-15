"""ChatBI 接口 Schema 导出。"""

from .datasource import (
    ChatbiDatasourceCreateRequest,
    ChatbiDatasourceExecuteSqlRequest,
    ChatbiDatasourceExecuteSqlResponse,
    ChatbiDatasourceFromFilesRequest,
    ChatbiDatasourceListQuery,
    ChatbiDatasourceListResponse,
    ChatbiDatasourcePreprocessResponse,
    ChatbiDatasourceRecordOut,
    ChatbiDatasourceUpdateRequest,
)

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
]
