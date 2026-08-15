"""ChatBI 问数服务异常（独立模块，避免与 query_pipeline 循环导入）。"""

from __future__ import annotations

from cogmait_shared.core.api_codes import ErrorCode, HttpStatus

from ..service_error import ServiceError


class ChatbiQueryServiceError(ServiceError):
    """问数 SSE 与详情接口异常。"""

    @classmethod
    def bad_request(cls, message: str) -> ChatbiQueryServiceError:
        return cls(
            message,
            status_code=HttpStatus.BAD_REQUEST,
            code=ErrorCode.PARAMS_INVALID,
        )

    @classmethod
    def not_found(cls, message: str = "记录不存在") -> ChatbiQueryServiceError:
        return cls(
            message,
            status_code=HttpStatus.NOT_FOUND,
            code=ErrorCode.NOT_FOUND,
        )

    @classmethod
    def system_error(cls, message: str) -> ChatbiQueryServiceError:
        return cls(
            message,
            status_code=HttpStatus.INTERNAL_ERROR,
            code=ErrorCode.SYSTEM_ERROR,
        )


__all__ = ["ChatbiQueryServiceError"]
