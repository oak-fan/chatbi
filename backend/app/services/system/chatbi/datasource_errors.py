"""ChatBI 数据源服务异常（独立模块，避免与 datasource 子包循环导入）。"""

from __future__ import annotations

from cogmait_shared.core.api_codes import ErrorCode, HttpStatus

from ..service_error import ServiceError


class ChatbiDatasourceServiceError(ServiceError):
    """ChatBI 数据源服务异常。"""

    @classmethod
    def bad_request(cls, message: str) -> ChatbiDatasourceServiceError:
        return cls(
            message,
            status_code=HttpStatus.BAD_REQUEST,
            code=ErrorCode.PARAMS_INVALID,
        )

    @classmethod
    def status_invalid(cls, message: str) -> ChatbiDatasourceServiceError:
        return cls(
            message,
            status_code=HttpStatus.CONFLICT,
            code=ErrorCode.STATUS_INVALID,
        )

    @classmethod
    def not_found(cls, message: str = "数据源不存在") -> ChatbiDatasourceServiceError:
        return cls(
            message,
            status_code=HttpStatus.NOT_FOUND,
            code=ErrorCode.NOT_FOUND,
        )

    @classmethod
    def connection_failed(
        cls,
        message: str,
        *,
        expose: bool = False,
    ) -> ChatbiDatasourceServiceError:
        return cls(
            message,
            status_code=HttpStatus.BAD_GATEWAY,
            code=ErrorCode.CONNECTION_FAILED,
            expose_message=expose,
        )

    @classmethod
    def system_error(cls, message: str) -> ChatbiDatasourceServiceError:
        return cls(
            message,
            status_code=HttpStatus.INTERNAL_ERROR,
            code=ErrorCode.SYSTEM_ERROR,
        )

    @classmethod
    def not_implemented(cls, message: str) -> ChatbiDatasourceServiceError:
        return cls(
            message,
            status_code=HttpStatus.NOT_IMPLEMENTED,
            code=ErrorCode.NOT_IMPLEMENTED,
        )


DbConnectionServiceError = ChatbiDatasourceServiceError

__all__ = ["ChatbiDatasourceServiceError", "DbConnectionServiceError"]
