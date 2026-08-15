"""ChatBI 预处理任务 Worker。"""

from __future__ import annotations

import argparse
import asyncio
import signal
from collections.abc import Coroutine
from socket import gethostname
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis

from cogmait_shared.cache import CacheRepository, CacheService
from cogmait_shared.db import UnitOfWork
from cogmait_shared.observability.logging import logger
from cogmait_shared.streaming import (
    RedisStreamConfig,
    RedisStreamConsumer,
    RedisWorker,
    StreamMessage,
    WorkerResult,
)

from ...constants.chatbi.datasource import (
    CHATBI_PREPROCESS_TASK_STREAM,
    CHATBI_PREPROCESS_WORKER_CLAIM_IDLE_COUNT,
)
from ...core.config import settings
from ...core.database import get_default_database
from ...core.redis import get_redis_client
from ...services.system.chatbi.datasource_service import ChatbiDatasourceService
from ...services.system.chatbi.vector import (
    build_chatbi_vector_settings,
    initialize_chatbi_vector_backend,
)
from ...services.system.content_extract import FileAccessService
from ...services.system.llm_service import get_default_llm_service

_WORKER_GROUP = "chatbi_preprocess_workers"
_TASK_LOCK_KEY_PREFIX = "chatbi:preprocess:task-lock"
_TASK_LOCK_TTL_SECONDS = 30 * 60
_TASK_LOCK_REFRESH_INTERVAL_SECONDS = 5 * 60


class _TaskLockRefreshLost(RuntimeError):
    """任务执行锁续期失败。"""


class _TaskExecutionLock:
    def __init__(self, cache: CacheService, *, task_id: int) -> None:
        self._cache = cache
        self._task_id = task_id
        self._token = uuid4().hex

    @property
    def key(self) -> str:
        return f"{_TASK_LOCK_KEY_PREFIX}:{self._task_id}"

    @property
    def task_id(self) -> int:
        return self._task_id

    async def acquire(self) -> bool:
        return await self._cache.acquire_lock(
            self.key,
            self._token,
            ttl_seconds=_TASK_LOCK_TTL_SECONDS,
        )

    async def refresh(self) -> bool:
        script = (
            "if redis.call('GET', KEYS[1]) == ARGV[1] then "
            "  return redis.call('EXPIRE', KEYS[1], ARGV[2]); "
            "else "
            "  return 0; "
            "end"
        )
        result = await self._cache.eval(
            script,
            [self.key],
            [self._token, _TASK_LOCK_TTL_SECONDS],
        )
        return int(result or 0) > 0

    async def release(self) -> None:
        await self._cache.release_lock(self.key, self._token)


async def _refresh_lock_until_done(lock: _TaskExecutionLock) -> None:
    while True:
        await asyncio.sleep(_TASK_LOCK_REFRESH_INTERVAL_SECONDS)
        try:
            refreshed = await lock.refresh()
        except Exception:
            logger.exception("ChatBI 预处理任务锁续期异常 task_id={}", lock.task_id)
            raise _TaskLockRefreshLost from None
        if not refreshed:
            logger.warning("ChatBI 预处理任务锁续期失败 task_id={}", lock.task_id)
            raise _TaskLockRefreshLost


async def _cancel_task(task: asyncio.Task[None], *, task_id: int) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("ChatBI 预处理任务取消后退出异常 task_id={}", task_id)


async def _run_with_lock_refresh(
    *,
    lock: _TaskExecutionLock,
    task_id: int,
    work: Coroutine[Any, Any, None],
) -> WorkerResult:
    work_task = asyncio.create_task(work)
    refresh_task = asyncio.create_task(_refresh_lock_until_done(lock))
    try:
        done, _pending = await asyncio.wait(
            {work_task, refresh_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if refresh_task in done:
            try:
                await refresh_task
            except _TaskLockRefreshLost:
                pass
            logger.warning("ChatBI 预处理任务锁已失效，保持消息待重试 task_id={}", task_id)
            if not work_task.done():
                await _cancel_task(work_task, task_id=task_id)
            else:
                try:
                    await work_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception(
                        "ChatBI 预处理任务锁失效时处理任务已异常退出 task_id={}",
                        task_id,
                    )
            return WorkerResult.retry()

        refresh_task.cancel()
        try:
            await refresh_task
        except asyncio.CancelledError:
            pass
        await work_task
        return WorkerResult.ack_and_delete()
    finally:
        for task in (work_task, refresh_task):
            if not task.done():
                await _cancel_task(task, task_id=task_id)


async def _process_preprocess_task_message(
    *,
    task_id: int,
    redis: Redis,
) -> None:
    database = get_default_database()
    async with database.get_session() as session:
        file_access_service = FileAccessService()
        try:
            service = ChatbiDatasourceService(
                unit_of_work=UnitOfWork(session),
                redis=redis,
                file_access_service=file_access_service,
                llm_service=get_default_llm_service(),
            )
            await service.process_preprocess_task(task_id)
        finally:
            await file_access_service.aclose()


async def handle_message(message: StreamMessage) -> WorkerResult:
    """处理单条 ChatBI 预处理任务消息。"""
    raw_task_id = message.payload.get("task_id")
    if isinstance(raw_task_id, bool) or not isinstance(raw_task_id, int):
        logger.warning("ChatBI 预处理消息缺少有效 task_id: {}", message.payload)
        return WorkerResult.ack_and_delete()

    redis = get_redis_client()
    lock = _TaskExecutionLock(_build_cache_service(redis), task_id=raw_task_id)
    if not await lock.acquire():
        logger.info("ChatBI 预处理任务仍在执行，保持消息待重试 task_id={}", raw_task_id)
        return WorkerResult.retry()

    try:
        return await _run_with_lock_refresh(
            lock=lock,
            task_id=raw_task_id,
            work=_process_preprocess_task_message(task_id=raw_task_id, redis=redis),
        )
    finally:
        try:
            await lock.release()
        except Exception:
            logger.exception("ChatBI 预处理任务锁释放失败 task_id={}", raw_task_id)


def _build_cache_service(redis: Redis) -> CacheService:
    return CacheService(CacheRepository(redis, key_prefix=settings.redis_key_prefix))


def create_worker(*, consumer_name: str, max_concurrency: int) -> RedisWorker:
    """创建 ChatBI 预处理 Stream Worker。"""
    consumer = RedisStreamConsumer(
        get_redis_client(),
        RedisStreamConfig(
            stream=CHATBI_PREPROCESS_TASK_STREAM,
            group=_WORKER_GROUP,
            consumer=consumer_name,
            key_prefix=settings.redis_key_prefix,
        ),
    )
    return RedisWorker(
        consumer,
        handlers={None: handle_message},
        default_handler=handle_message,
        max_concurrency=max_concurrency,
        idle_sleep=0.5,
        claim_idle_ms=60_000,
        claim_idle_interval=30.0,
        claim_idle_count=CHATBI_PREPROCESS_WORKER_CLAIM_IDLE_COUNT,
        delete_after_ack=True,
    )


async def run_worker(*, consumer_name: str, max_concurrency: int) -> None:
    """运行 ChatBI 预处理 Worker 主循环。"""
    database = get_default_database()
    database.initialize()
    initialize_chatbi_vector_backend(build_chatbi_vector_settings(settings))
    worker = create_worker(
        consumer_name=consumer_name,
        max_concurrency=max_concurrency,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.request_shutdown)
        except NotImplementedError:
            pass

    try:
        await worker.run()
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="ChatBI 预处理 Worker")
    parser.add_argument(
        "--consumer-name",
        type=str,
        default=f"{gethostname()}-chatbi-preprocess-worker",
        help="Redis Streams consumer 名称",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=2,
        help="单进程最大并发数",
    )
    args = parser.parse_args()

    asyncio.run(
        run_worker(
            consumer_name=args.consumer_name,
            max_concurrency=args.max_concurrency,
        )
    )


if __name__ == "__main__":
    main()
