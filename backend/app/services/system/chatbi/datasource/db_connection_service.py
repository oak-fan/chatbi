"""ChatBI 数据源连接解密、连接器选择与只读执行。"""

from __future__ import annotations

from typing import Any

from cogmait_shared.observability.logging import logger

from .....constants.chatbi.datasource import (
    CHATBI_DEFAULT_SCHEMA_NAME,
    CHATBI_EXECUTE_SQL_MAX_ROWS,
    CHATBI_EXECUTE_SQL_TIMEOUT_SECONDS,
)
from .....domain.system.chatbi import ChatbiDatasourceConnectionRecord
from .....repositories.system.chatbi import ChatbiDatasourceRepository
from ..datasource_errors import ChatbiDatasourceServiceError
from .connectors import ConnectionTestError, UnsupportedDatasourceTypeError, get_connector
from .credential_encryption_service import ChatbiCredentialEncryptionService


class ChatbiDbConnectionService:
    """统一封装解密、连接器选择与只读执行。"""

    def __init__(
        self,
        *,
        datasource_repo: ChatbiDatasourceRepository,
        encryption: ChatbiCredentialEncryptionService,
    ) -> None:
        self._repo = datasource_repo
        self._encryption = encryption

    def build_connector_config(self, record: ChatbiDatasourceConnectionRecord) -> dict[str, Any]:
        """将连接记录解密为连接器所需的 host/port 等字典。"""

        try:
            password = self._encryption.decrypt(record.encrypted_password)
        except ValueError as exc:
            raise ChatbiDatasourceServiceError.system_error("数据源凭证解密失败") from exc
        return {
            "host": record.host,
            "port": record.port,
            "database": record.database,
            "schema_name": record.schema_name or CHATBI_DEFAULT_SCHEMA_NAME,
            "username": record.username,
            "password": password,
            "extra_params": dict(record.extra_params or {}),
        }

    async def test_connection_for_user(self, datasource_id: int, user_id: int) -> None:
        """校验归属后，对目标库执行 SELECT 1。"""

        conn = await self._repo.get_connection_for_user(datasource_id, user_id)
        if conn is None:
            raise ChatbiDatasourceServiceError.not_found()
        connector = self._get_connector_safe(conn.connector_type)
        cfg = self.build_connector_config(conn)
        try:
            await connector.test_connection(cfg)
        except ConnectionTestError as exc:
            logger.warning(
                "ChatBI datasource connection test failed datasource_id={} user_id={} error={}",
                datasource_id,
                user_id,
                str(exc),
            )
            raise ChatbiDatasourceServiceError.connection_failed(
                "数据库连接失败，请检查连接配置",
            ) from exc

    async def execute_readonly_sql(
        self,
        *,
        datasource_id: int,
        user_id: int,
        sql: str,
        max_rows: int = CHATBI_EXECUTE_SQL_MAX_ROWS,
        timeout_seconds: float = CHATBI_EXECUTE_SQL_TIMEOUT_SECONDS,
    ) -> tuple[list[str], list[dict[str, Any]], bool]:
        """只读事务执行单条 SQL，并按 max_rows 截断。"""

        conn = await self._repo.get_connection_for_user(datasource_id, user_id)
        if conn is None:
            raise ChatbiDatasourceServiceError.not_found()
        connector = self._get_connector_safe(conn.connector_type)
        cfg = self.build_connector_config(conn)
        try:
            columns, rows = await connector.execute_readonly_sql(
                cfg,
                sql,
                max_rows=max_rows,
                timeout_seconds=timeout_seconds,
            )
        except ConnectionTestError as exc:
            raise ChatbiDatasourceServiceError.connection_failed(
                str(exc),
                expose=True,
            ) from exc
        except ValueError as exc:
            raise ChatbiDatasourceServiceError.bad_request(str(exc)) from exc
        truncated = len(rows) > max_rows
        if truncated:
            rows = rows[:max_rows]
        return columns, rows, truncated

    async def execute_readonly_sql_by_datasource(
        self,
        *,
        datasource_id: int,
        sql: str,
        max_rows: int = CHATBI_EXECUTE_SQL_MAX_ROWS,
        timeout_seconds: float = CHATBI_EXECUTE_SQL_TIMEOUT_SECONDS,
    ) -> tuple[list[str], list[dict[str, Any]], bool]:
        """已完成应用层授权后，按数据源 ID 只读执行 SQL。"""

        conn = await self._repo.get_connection_by_id(datasource_id)
        if conn is None:
            raise ChatbiDatasourceServiceError.not_found()
        connector = self._get_connector_safe(conn.connector_type)
        cfg = self.build_connector_config(conn)
        try:
            columns, rows = await connector.execute_readonly_sql(
                cfg,
                sql,
                max_rows=max_rows,
                timeout_seconds=timeout_seconds,
            )
        except ConnectionTestError as exc:
            raise ChatbiDatasourceServiceError.connection_failed(
                str(exc),
                expose=True,
            ) from exc
        except ValueError as exc:
            raise ChatbiDatasourceServiceError.bad_request(str(exc)) from exc
        truncated = len(rows) > max_rows
        if truncated:
            rows = rows[:max_rows]
        return columns, rows, truncated

    def _get_connector_safe(self, type_code: str):
        try:
            return get_connector(type_code)
        except UnsupportedDatasourceTypeError as exc:
            raise ChatbiDatasourceServiceError.bad_request(str(exc)) from exc


__all__ = ["ChatbiDbConnectionService"]
