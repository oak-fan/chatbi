"""cogmait-chatbi 依赖注入。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import Depends, Request
from redis.asyncio import Redis

from cogmait_shared.api import (
    build_database_dependency,
    build_db_session_dependency,
    build_unit_of_work_dependency,
    get_database_from_app_state,
    get_response_factory,
)
from cogmait_shared.cache import CacheOps, CacheRepository, CacheService
from cogmait_shared.db import Database

from ..observability import ObservabilityProvider, get_default_observability_provider
from ..services.system.chatbi.benchmark_service import ChatbiBenchmarkService
from ..services.system.chatbi.business_knowledge_service import ChatbiBusinessKnowledgeService
from ..services.system.chatbi.datasource_service import ChatbiDatasourceService
from ..services.system.chatbi.qsql_service import ChatbiQsqlService
from ..services.system.chatbi.query_service import ChatbiQueryService
from ..services.system.content_extract import FileAccessService
from ..services.system.llm_service import LLMService, get_default_llm_service
from ..services.system.rewrite import RewriteService
from ..services.system.vector_store import VectorStoreSettings
from .config import settings
from .redis import get_redis_client

ChatbiQueryServiceStreamFactory = Callable[[], AbstractAsyncContextManager[ChatbiQueryService]]


def get_llm_service() -> LLMService:
    return get_default_llm_service()


def get_observability_provider() -> ObservabilityProvider:
    return get_default_observability_provider()


def get_rewrite_service(
    llm_service: LLMService = Depends(get_llm_service),
    observability: ObservabilityProvider = Depends(get_observability_provider),
) -> RewriteService:
    return RewriteService(llm_service=llm_service, observability=observability)


async def get_file_access_service() -> AsyncIterator[FileAccessService]:
    service = FileAccessService()
    try:
        yield service
    finally:
        await service.aclose()


get_database = build_database_dependency(expected_type=Database)
get_db = build_db_session_dependency(get_database)
get_unit_of_work = build_unit_of_work_dependency(get_db)


def get_redis() -> Redis:
    return get_redis_client()


def get_vector_store_settings(request: Request) -> VectorStoreSettings:
    return get_database_from_app_state(
        request,
        expected_type=VectorStoreSettings,
        state_key="vector_store_settings",
        missing_message="向量配置未在 app.state 上初始化",
    )


def get_cache_repository(
    redis: Redis = Depends(get_redis),
) -> CacheRepository:
    return CacheRepository(redis, key_prefix=settings.redis_key_prefix)


def get_cache_service(
    repo: CacheRepository = Depends(get_cache_repository),
) -> CacheOps:
    return CacheService(repo)


def get_chatbi_datasource_service(
    unit_of_work=Depends(get_unit_of_work),
    redis: Redis = Depends(get_redis),
    file_access_service: FileAccessService = Depends(get_file_access_service),
    llm_service: LLMService = Depends(get_llm_service),
) -> ChatbiDatasourceService:
    return ChatbiDatasourceService(
        unit_of_work=unit_of_work,
        redis=redis,
        file_access_service=file_access_service,
        llm_service=llm_service,
    )


def get_chatbi_qsql_service(
    unit_of_work=Depends(get_unit_of_work),
    llm_service: LLMService = Depends(get_llm_service),
) -> ChatbiQsqlService:
    return ChatbiQsqlService(unit_of_work=unit_of_work, llm_service=llm_service)


def get_chatbi_business_knowledge_service(
    unit_of_work=Depends(get_unit_of_work),
    llm_service: LLMService = Depends(get_llm_service),
) -> ChatbiBusinessKnowledgeService:
    return ChatbiBusinessKnowledgeService(
        unit_of_work=unit_of_work,
        llm_service=llm_service,
    )


def get_chatbi_benchmark_service(
    unit_of_work=Depends(get_unit_of_work),
    redis: Redis = Depends(get_redis),
    llm_service: LLMService = Depends(get_llm_service),
    rewrite_service: RewriteService = Depends(get_rewrite_service),
) -> ChatbiBenchmarkService:
    return ChatbiBenchmarkService(
        unit_of_work=unit_of_work,
        redis=redis,
        llm_service=llm_service,
        rewrite_service=rewrite_service,
    )


def get_chatbi_query_service(
    unit_of_work=Depends(get_unit_of_work),
    redis: Redis = Depends(get_redis),
    llm_service: LLMService = Depends(get_llm_service),
    rewrite_service: RewriteService = Depends(get_rewrite_service),
    observability: ObservabilityProvider = Depends(get_observability_provider),
) -> ChatbiQueryService:
    return ChatbiQueryService(
        unit_of_work=unit_of_work,
        redis=redis,
        llm_service=llm_service,
        rewrite_service=rewrite_service,
        observability=observability,
    )


def get_chatbi_query_service_stream_factory(
    database: Database = Depends(get_database),
    redis: Redis = Depends(get_redis),
    llm_service: LLMService = Depends(get_llm_service),
) -> ChatbiQueryServiceStreamFactory:
    def factory() -> AbstractAsyncContextManager[ChatbiQueryService]:
        return _chatbi_query_service_stream_context(
            database=database,
            redis=redis,
            llm_service=llm_service,
        )

    return factory


@asynccontextmanager
async def _chatbi_query_service_stream_context(
    *,
    database: Database,
    redis: Redis,
    llm_service: LLMService,
) -> AsyncIterator[ChatbiQueryService]:
    async with database.get_session() as db:
        unit_of_work = get_unit_of_work(db)
        yield ChatbiQueryService(
            unit_of_work=unit_of_work,
            redis=redis,
            llm_service=llm_service,
            rewrite_service=RewriteService(
                llm_service=llm_service,
                observability=get_observability_provider(),
            ),
            observability=get_observability_provider(),
        )


__all__ = [
    "get_chatbi_business_knowledge_service",
    "get_chatbi_benchmark_service",
    "get_chatbi_datasource_service",
    "get_chatbi_query_service",
    "get_chatbi_query_service_stream_factory",
    "get_chatbi_qsql_service",
    "get_cache_service",
    "get_cache_repository",
    "get_database",
    "get_db",
    "get_file_access_service",
    "get_llm_service",
    "get_observability_provider",
    "get_redis",
    "get_response_factory",
    "get_unit_of_work",
    "get_vector_store_settings",
]
