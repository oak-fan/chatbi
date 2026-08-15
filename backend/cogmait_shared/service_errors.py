"""跨服务共享的服务层异常。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Self

from .core.api_codes import ErrorCode, HttpStatus


class ServiceError(Exception):
    """统一的服务异常结构，便于 API 层一致处理。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        code: int = 40000,
        expose_message: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.expose_message = expose_message

    @classmethod
    def bad_request(cls, message: str) -> Self:
        """构造统一的参数校验异常。"""

        return cls(
            message,
            status_code=HttpStatus.BAD_REQUEST,
            code=ErrorCode.PARAMS_INVALID,
        )

    @classmethod
    def bad_gateway(cls, message: str) -> Self:
        """构造统一的上游服务异常。"""

        return cls(
            message,
            status_code=HttpStatus.BAD_GATEWAY,
            code=ErrorCode.CONNECTION_FAILED,
        )

    @classmethod
    def system_error(cls, message: str) -> Self:
        """构造统一的系统异常。"""

        return cls(
            message,
            status_code=HttpStatus.INTERNAL_ERROR,
            code=ErrorCode.SYSTEM_ERROR,
        )

    @classmethod
    def from_value_error(cls, exc: ValueError) -> Self:
        """将 ValueError 包装为参数校验异常。"""

        return cls.bad_request(str(exc))

    @classmethod
    def not_found(cls, message: str = "资源不存在") -> Self:
        """构造统一的资源不存在异常。"""

        return cls(
            message,
            status_code=HttpStatus.NOT_FOUND,
            code=ErrorCode.NOT_FOUND,
        )


@contextmanager
def wrap_value_error(error_cls: type[ServiceError]) -> Iterator[None]:
    """将代码块中的 ValueError 自动包装为对应的 ServiceError 子类。"""

    try:
        yield
    except ValueError as exc:
        raise error_cls.from_value_error(exc) from exc


__all__ = ["ServiceError", "wrap_value_error"]
