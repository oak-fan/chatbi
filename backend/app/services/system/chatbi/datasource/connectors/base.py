"""数据源连接器抽象：按库类型采集结构与执行 SQL。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ......domain.system.chatbi.db_schema import ChatbiDbSchemaRecord


class BaseDatasourceConnector(ABC):
    """外部库连接器协议实现基类。"""

    @abstractmethod
    async def test_connection(self, config: dict[str, Any]) -> bool:
        """执行 SELECT 1，成功返回 True。"""

    @abstractmethod
    async def get_structure(self, config: dict[str, Any]) -> ChatbiDbSchemaRecord:
        """获取库表结构，返回统一 db_schema 结构（description 可为空）。"""

    @abstractmethod
    async def execute_readonly_sql(
        self,
        config: dict[str, Any],
        sql: str,
        *,
        max_rows: int | None = None,
        timeout_seconds: float | None = None,
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """只读事务执行单条 SQL，返回列名与行字典列表。"""

    @abstractmethod
    async def execute_sql(
        self,
        config: dict[str, Any],
        sql: str,
    ) -> None:
        """读写事务执行 SQL（建表/灌数等）。"""

    @abstractmethod
    async def execute_sql_transaction(
        self,
        config: dict[str, Any],
        statements: list[str],
    ) -> None:
        """在同一个事务内执行多条写 SQL。"""


__all__ = ["BaseDatasourceConnector"]
