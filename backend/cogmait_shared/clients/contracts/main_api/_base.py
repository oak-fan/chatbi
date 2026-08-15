"""main_api 内部客户端基类。"""

from __future__ import annotations

import httpx

from ...core import (
    InternalServiceClient,
    resolve_internal_service_base_url,
    resolve_internal_service_token,
)


class MainApiInternalClient(InternalServiceClient):
    """统一 main_api 内部客户端的连接配置。"""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 10.0,
        api_token: str | None = None,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=resolve_internal_service_base_url(
                explicit_base_url=base_url,
                env_var="MAIN_API_BASE_URL",
            ),
            api_token=resolve_internal_service_token(api_token),
            timeout=timeout,
            client=client,
            transport=transport,
        )


__all__ = ["MainApiInternalClient"]
