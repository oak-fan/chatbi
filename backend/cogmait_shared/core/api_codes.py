"""API status and error code constants without Web framework dependencies."""

from __future__ import annotations


class HttpStatus:
    """常用 HTTP 状态码。"""

    # 请求成功。
    OK = 200
    # 请求参数错误或业务入参不合法。
    BAD_REQUEST = 400
    # 未认证或认证凭证无效。
    UNAUTHORIZED = 401
    # 已认证但无权访问当前资源。
    FORBIDDEN = 403
    # 资源不存在。
    NOT_FOUND = 404
    # 资源状态冲突，例如唯一性冲突或当前状态不允许操作。
    CONFLICT = 409
    # 资源被锁定，通常用于账号锁定等场景。
    LOCKED = 423
    # 请求过于频繁，触发限流。
    TOO_MANY_REQUESTS = 429
    # 请求结构可解析，但字段校验失败。
    UNPROCESSABLE_ENTITY = 422
    # 服务端内部错误。
    INTERNAL_ERROR = 500
    # 功能未实现。
    NOT_IMPLEMENTED = 501
    # 网关访问上游服务失败。
    BAD_GATEWAY = 502
    # 服务暂不可用，通常用于依赖不可用或熔断。
    SERVICE_UNAVAILABLE = 503
    # 网关访问上游服务超时。
    GATEWAY_TIMEOUT = 504


class ErrorCode:
    """项目统一错误码。"""

    # 参数缺失，必填项未提供。
    PARAMS_REQUIRED = 40001
    # 参数非法，格式或取值不合法。
    PARAMS_INVALID = 40002
    # 状态非法，当前资源状态不允许执行该操作。
    STATUS_INVALID = 40003
    # 资源已存在，通常用于唯一性冲突。
    ALREADY_EXISTS = 40010
    # 系统错误，服务端异常。
    SYSTEM_ERROR = 50000
    # 上游或外部依赖连接失败。
    CONNECTION_FAILED = 50201
    # 功能未实现。
    NOT_IMPLEMENTED = 50100

    # 凭证错误，例如账号或密码错误。
    INVALID_CREDENTIALS = 40101
    # 刷新令牌无效。
    INVALID_REFRESH_TOKEN = 40102
    # 账号已禁用。
    ACCOUNT_DISABLED = 40301
    # 当前账号类型不允许访问。
    ACCOUNT_TYPE_FORBIDDEN = 40302
    # 权限不足。
    PERMISSION_DENIED = 40303
    # 账号已锁定。
    ACCOUNT_LOCKED = 42300

    # 资源不存在。
    NOT_FOUND = 40404


__all__ = ["ErrorCode", "HttpStatus"]
