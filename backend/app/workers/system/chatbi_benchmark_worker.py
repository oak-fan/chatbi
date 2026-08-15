"""ChatBI 基准评价任务 Worker。"""

from __future__ import annotations

import argparse
import asyncio
import signal
from socket import gethostname

from cogmait_shared.db import UnitOfWork
from cogmait_shared.observability.logging import logger
from cogmait_shared.streaming import (
    RedisStreamConfig,
    RedisStreamConsumer,
    RedisWorker,
    StreamMessage,
    WorkerResult,
)

from ...core.config import settings
from ...core.database import get_default_database
from ...core.redis import get_redis_client
from ...observability import get_default_observability_provider
from ...services.system.chatbi.benchmark_service import (
    CHATBI_BENCHMARK_TASK_ACTION_RERUN_CASE,
    CHATBI_BENCHMARK_TASK_STREAM,
    ChatbiBenchmarkService,
)
from ...services.system.llm_service import get_default_llm_service
from ...services.system.rewrite import RewriteService

_WORKER_GROUP = "chatbi_benchmark_workers"


async def _process_run(run_id: int) -> None:
    database = get_default_database()
    redis = get_redis_client()
    llm_service = get_default_llm_service()
    async with database.get_session() as session:
        service = ChatbiBenchmarkService(
            unit_of_work=UnitOfWork(session),
            redis=redis,
            llm_service=llm_service,
            rewrite_service=RewriteService(
                llm_service=llm_service,
                observability=get_default_observability_provider(),
            ),
            database=database,
        )
        await service.process_run(run_id)


async def _process_rerun(run_id: int, result_id: int) -> None:
    database = get_default_database()
    redis = get_redis_client()
    llm_service = get_default_llm_service()
    async with database.get_session() as session:
        service = ChatbiBenchmarkService(
            unit_of_work=UnitOfWork(session),
            redis=redis,
            llm_service=llm_service,
            rewrite_service=RewriteService(
                llm_service=llm_service,
                observability=get_default_observability_provider(),
            ),
            database=database,
        )
        await service.process_rerun_case(run_id, result_id)


async def handle_message(message: StreamMessage) -> WorkerResult:
    raw_run_id = message.payload.get("run_id")
    if isinstance(raw_run_id, bool) or not isinstance(raw_run_id, int):
        logger.warning("ChatBI benchmark 消息缺少有效 run_id: {}", message.payload)
        return WorkerResult.ack_and_delete()
    task_action = message.payload.get("task_action")
    if task_action == CHATBI_BENCHMARK_TASK_ACTION_RERUN_CASE:
        raw_result_id = message.payload.get("result_id")
        if isinstance(raw_result_id, bool) or not isinstance(raw_result_id, int):
            logger.warning("ChatBI benchmark 重跑消息缺少有效 result_id: {}", message.payload)
            return WorkerResult.ack_and_delete()
        await _process_rerun(raw_run_id, raw_result_id)
        return WorkerResult.ack_and_delete()
    await _process_run(raw_run_id)
    return WorkerResult.ack_and_delete()


def create_worker(*, consumer_name: str, max_concurrency: int) -> RedisWorker:
    consumer = RedisStreamConsumer(
        get_redis_client(),
        RedisStreamConfig(
            stream=CHATBI_BENCHMARK_TASK_STREAM,
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
        delete_after_ack=True,
    )


async def run_worker(*, consumer_name: str, max_concurrency: int) -> None:
    database = get_default_database()
    database.initialize()
    worker = create_worker(consumer_name=consumer_name, max_concurrency=max_concurrency)
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
    parser = argparse.ArgumentParser(description="ChatBI 基准评价 Worker")
    parser.add_argument(
        "--consumer-name",
        type=str,
        default=f"{gethostname()}-chatbi-benchmark-worker",
    )
    parser.add_argument("--max-concurrency", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(
        run_worker(
            consumer_name=args.consumer_name,
            max_concurrency=args.max_concurrency,
        )
    )


if __name__ == "__main__":
    main()
