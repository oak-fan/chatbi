"""ChatBI 问数只读 SQL 执行封装。"""

from __future__ import annotations

from typing import Any

from .....constants.chatbi.datasource import CHATBI_EXECUTE_SQL_MAX_ROWS
from ..datasource.db_connection_service import ChatbiDbConnectionService
from ..datasource_errors import ChatbiDatasourceServiceError


class ChatbiSqlExecutor:
    """对数据源执行只读 SQL。"""

    def __init__(self, *, db_connection: ChatbiDbConnectionService) -> None:
        self._db = db_connection

    async def execute(
        self,
        *,
        datasource_id: int,
        user_id: int,
        sql: str,
        max_rows: int = CHATBI_EXECUTE_SQL_MAX_ROWS,
    ) -> tuple[list[str], list[dict[str, Any]], bool]:
        try:
            return await self._db.execute_readonly_sql(
                datasource_id=datasource_id,
                user_id=user_id,
                sql=sql,
                max_rows=max_rows,
            )
        except ChatbiDatasourceServiceError:
            raise
        except Exception as exc:
            raise ChatbiDatasourceServiceError.system_error(str(exc)) from exc


__all__ = ["ChatbiSqlExecutor"]
