"""API contract and HTTP helpers."""

from ..core.api_codes import ErrorCode, HttpStatus
from .dependencies import (
    build_database_dependency,
    build_db_session_dependency,
    build_unit_of_work_dependency,
    get_database_from_app_state,
    get_response_factory,
)
from .errors import EXPOSE_ERROR_MESSAGE_HEADER, ServiceErrorProtocol, raise_service_error
from .exception_handlers import register_exception_handlers
from .middleware import RequestIdMiddleware
from .pagination import build_page_payload
from .query_params import parse_optional_query_bool, parse_query_bool
from .response import (
    DEFAULT_ERROR_MESSAGE,
    DEFAULT_SUCCESS_MESSAGE,
    ResponseEnvelope,
    ResponseFactory,
    error,
    success,
)
from .response_schema import EmptyPayload, ResponseSchema
from .service_errors import (
    ServiceError,
    build_bad_request_error,
    build_domain_input,
    build_not_found_error,
    raise_unreachable,
    run_service_call,
    success_response,
    wrap_value_error,
)
from .types import SnowflakeID

__all__ = [
    "DEFAULT_ERROR_MESSAGE",
    "DEFAULT_SUCCESS_MESSAGE",
    "EmptyPayload",
    "ErrorCode",
    "EXPOSE_ERROR_MESSAGE_HEADER",
    "HttpStatus",
    "RequestIdMiddleware",
    "ResponseEnvelope",
    "ResponseFactory",
    "ResponseSchema",
    "ServiceError",
    "ServiceErrorProtocol",
    "SnowflakeID",
    "build_bad_request_error",
    "build_database_dependency",
    "build_db_session_dependency",
    "build_domain_input",
    "build_page_payload",
    "build_not_found_error",
    "build_unit_of_work_dependency",
    "error",
    "get_database_from_app_state",
    "get_response_factory",
    "parse_optional_query_bool",
    "parse_query_bool",
    "raise_unreachable",
    "raise_service_error",
    "register_exception_handlers",
    "run_service_call",
    "success",
    "success_response",
    "wrap_value_error",
]
