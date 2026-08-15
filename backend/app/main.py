"""cogmait-chatbi FastAPI 应用入口。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from cogmait_shared.api.exception_handlers import register_exception_handlers
from cogmait_shared.api.middleware import RequestIdMiddleware
from cogmait_shared.core.id_generator import SnowflakeConfig, configure_snowflake_generator

from .api import create_api_router
from .core.config import settings
from .core.database import Database
from .core.logging import init_logging
from .observability import shutdown_default_observability_provider
from .services.system.chatbi.vector import (
    build_chatbi_vector_settings,
    initialize_chatbi_vector_backend,
)
from .services.system.vector_store import build_vector_store_settings, initialize_vector_backend


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_logging()
    database = Database(database_url=settings.database_url, sql_echo=settings.sql_echo)
    database.initialize()
    try:
        app.state.database = database
        app.state.vector_store_settings = build_vector_store_settings(settings)
        initialize_vector_backend(app.state.vector_store_settings)
        app.state.chatbi_vector_store_settings = build_chatbi_vector_settings(settings)
        initialize_chatbi_vector_backend(app.state.chatbi_vector_store_settings)
        yield
    finally:
        try:
            shutdown_default_observability_provider()
        finally:
            await database.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CogmAIT ChatBI",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    configure_snowflake_generator(
        datacenter_id=settings.snowflake_datacenter_id,
        worker_id=settings.snowflake_worker_id,
        config=SnowflakeConfig(),
    )

    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(create_api_router())

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
