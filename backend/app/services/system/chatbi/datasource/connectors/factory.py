"""ChatBI 数据源连接器工厂。"""

from __future__ import annotations

from ......domain.system.chatbi import DataSourceType
from .base import BaseDatasourceConnector
from .exceptions import UnsupportedDatasourceTypeError
from .mysql import MySQLConnector
from .postgresql import PostgreSQLConnector
from .sqlite import SQLiteConnector


def get_connector(type_code: str) -> BaseDatasourceConnector:
    """按领域 DataSourceType 返回具体连接器实例。"""
    if type_code == DataSourceType.POSTGRESQL.value:
        return PostgreSQLConnector()
    if type_code == DataSourceType.SQLITE.value:
        return SQLiteConnector()
    if type_code == DataSourceType.MYSQL.value:
        return MySQLConnector()
    raise UnsupportedDatasourceTypeError(type_code)


__all__ = ["get_connector"]
