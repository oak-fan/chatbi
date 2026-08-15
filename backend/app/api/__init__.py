"""API routers for cogmait-chatbi."""

from fastapi import APIRouter

from .system import routers as system_routers


def create_api_router() -> APIRouter:
    """构建对外 API 路由。"""

    router = APIRouter()
    api_v1_router = APIRouter(prefix="/api/v1")
    for sub_router in system_routers:
        api_v1_router.include_router(sub_router)
    router.include_router(api_v1_router)
    return router


__all__ = ["create_api_router"]
