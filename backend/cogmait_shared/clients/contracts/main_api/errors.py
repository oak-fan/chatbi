"""平台内部客户端公共错误类型。"""

from __future__ import annotations

from ...core import ServiceClientError

__all__ = [
    "ConfigClientError",
    "DictClientError",
    "FileClientError",
    "NotificationClientError",
    "UserClientError",
]


class ConfigClientError(ServiceClientError):
    """系统参数客户端异常。"""


class DictClientError(ServiceClientError):
    """字典客户端异常。"""


class FileClientError(ServiceClientError):
    """文件客户端异常。"""


class NotificationClientError(ServiceClientError):
    """通知客户端异常。"""


class UserClientError(ServiceClientError):
    """用户客户端异常。"""
