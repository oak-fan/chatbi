"""通用客户端底座。"""

__all__ = [
    "InternalAPICall",
    "InternalServiceClient",
    "ServiceClientError",
    "ServiceHttpClient",
    "resolve_internal_service_base_url",
    "resolve_internal_service_token",
]

from .auth import resolve_internal_service_token
from .base import InternalServiceClient
from .transport import (
    InternalAPICall,
    ServiceClientError,
    ServiceHttpClient,
    resolve_internal_service_base_url,
)
