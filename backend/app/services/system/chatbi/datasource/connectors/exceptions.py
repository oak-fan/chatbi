"""ChatBI 数据源连接器运行时异常。"""

from __future__ import annotations


class ConnectionTestError(Exception):
    """连接测试失败。"""


class UnsupportedDatasourceTypeError(Exception):
    """不支持的数据源类型。"""


__all__ = ["ConnectionTestError", "UnsupportedDatasourceTypeError"]
