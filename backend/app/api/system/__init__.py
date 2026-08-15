"""ChatBI API routers."""

from .chatbi import router as chatbi_router

routers = (chatbi_router,)

__all__ = ["routers"]
