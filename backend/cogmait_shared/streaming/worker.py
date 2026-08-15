"""通用 Redis Streams Worker 封装。

该模块基于多服务 Worker 进程的通用要求，实现可复用的异步执行器。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from redis.exceptions import RedisError

from ..observability.logging import logger
from .models import StreamMessage
from .worker_options import DEFAULT_WORKER_MAX_RETRIES, WorkerOptions
from .worker_processor import WorkerMessageProcessor, is_fatal_base_exception
from .worker_runtime import MessageAttemptTracker, WindowedErrorLogger


class StreamWorkerConsumer(Protocol):
    """RedisWorker 依赖的最小 consumer 协议。"""

    async def poll(self) -> list[StreamMessage]: ...

    async def ack(self, *message_ids: str) -> int: ...

    async def delete(self, *message_ids: str) -> int: ...

    async def claim_idle(
        self,
        *,
        min_idle_ms: int,
        count: int | None = None,
        start: str = "0-0",
    ) -> tuple[list[StreamMessage], str]: ...


@dataclass(slots=True)
class WorkerResult:
    """处理单条消息后的决策。"""

    ack: bool = True
    delete: bool = False

    @classmethod
    def ack_only(cls) -> WorkerResult:
        """工厂方法：仅确认消息。"""
        return cls(ack=True, delete=False)

    @classmethod
    def ack_and_delete(cls) -> WorkerResult:
        """工厂方法：确认后立即从流中删除消息。"""
        return cls(ack=True, delete=True)

    @classmethod
    def retry(cls) -> WorkerResult:
        """工厂方法：保持 pending，等待后续重试。"""
        return cls(ack=False, delete=False)


@dataclass(slots=True)
class WorkerStats:
    """Worker 运行时的统计数据，便于对外暴露监控指标。"""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    retried: int = 0


WorkerHandler = Callable[[StreamMessage], Awaitable[WorkerResult | None] | WorkerResult | None]
WorkerErrorHandler = Callable[
    [StreamMessage, BaseException],
    Awaitable[WorkerResult | None] | WorkerResult | None,
]
DeadLetterHandler = Callable[
    [StreamMessage, int, str],
    Awaitable[None] | None,
]
_RECOVERABLE_STREAM_INFRA_ERRORS = (
    RedisError,
    ConnectionError,
    TimeoutError,
    OSError,
)


class RedisWorker:
    """通用 Redis Streams Worker，负责拉取消息、调度处理并自动 ack。"""

    _ERROR_LOG_WINDOW_SECONDS = 30.0
    _ERROR_LOG_BURST_LIMIT = 5
    _MESSAGE_ATTEMPT_TTL_SECONDS = 6 * 60 * 60
    _MESSAGE_ATTEMPT_MAX_ENTRIES = 50_000
    _MESSAGE_ATTEMPT_PRUNE_INTERVAL_SECONDS = 60.0

    def __init__(
        self,
        consumer: StreamWorkerConsumer,
        *,
        handlers: dict[str | None, WorkerHandler] | None = None,
        default_handler: WorkerHandler | None = None,
        error_handler: WorkerErrorHandler | None = None,
        max_concurrency: int = 1,
        idle_sleep: float = 0.5,
        ack_on_error: bool = False,
        ack_unknown_task: bool = False,
        delete_after_ack: bool = False,
        max_retries: int | None = DEFAULT_WORKER_MAX_RETRIES,
        dead_letter_handler: DeadLetterHandler | None = None,
        claim_idle_ms: int | None = None,
        claim_idle_interval: float = 60.0,
        claim_idle_count: int = 20,
    ) -> None:
        """初始化 Worker。

        Args:
            consumer: 共享的 RedisStreamConsumer。
            handlers: `task_type -> handler` 映射。
            default_handler: 未命中映射时的兜底处理器。
            error_handler: 自定义异常处理逻辑，可决定是否 ack。
            max_concurrency: 并发执行的消息数量上限。
            idle_sleep: 无消息时的休眠时间，避免空轮询。
            ack_on_error: handler 抛出异常且无自定义 error_handler 时是否 ack。
            ack_unknown_task: 未注册 task_type 时是否自动 ack（默认 False，保持 pending 便于排查）。
            delete_after_ack: 成功 ack 后是否自动删除消息，以免 Stream 膨胀。
            max_retries: 单条消息在当前 Worker 生命周期内可处理的最大次数（包含首次），
                默认 3 次；显式传入 None 表示不由通用 Worker 收敛。
            dead_letter_handler: 达到最大重试后触发的死信处理回调（不影响 ack 收敛）。
            claim_idle_ms: 启用 `XAUTOCLAIM` 自愈时的最小 idle 毫秒（None 表示关闭）。
            claim_idle_interval: 自愈间隔秒数，避免频繁打扰 Redis。
            claim_idle_count: 每次自愈时认领的最大消息数量。
        """
        options = WorkerOptions(
            max_concurrency=max_concurrency,
            idle_sleep=idle_sleep,
            ack_on_error=ack_on_error,
            ack_unknown_task=ack_unknown_task,
            delete_after_ack=delete_after_ack,
            max_retries=max_retries,
            dead_letter_handler=dead_letter_handler,
            claim_idle_ms=claim_idle_ms,
            claim_idle_interval=claim_idle_interval,
            claim_idle_count=claim_idle_count,
        )
        options.validate()

        self._consumer = consumer
        self._handlers: dict[str | None, WorkerHandler] = dict(handlers or {})
        self._default_handler = default_handler
        self._error_handler = error_handler
        self._max_concurrency = options.max_concurrency
        self._idle_sleep = float(options.idle_sleep)
        self._ack_on_error = options.ack_on_error
        self._ack_unknown_task = options.ack_unknown_task
        self._delete_after_ack = options.delete_after_ack
        self._max_retries = options.max_retries
        self._dead_letter_handler = dead_letter_handler
        self._claim_idle_ms = options.claim_idle_ms
        self._claim_idle_interval = float(options.claim_idle_interval)
        self._claim_idle_count = options.claim_idle_count

        self._init_runtime_state(max_concurrency=options.max_concurrency)

    def _init_runtime_state(self, *, max_concurrency: int) -> None:
        self._stats = WorkerStats()
        self._stop_event = asyncio.Event()
        self._tasks: set[asyncio.Task[None]] = set()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._last_claim_ts = 0.0
        self._claim_idle_start = "0-0"
        self._message_attempt_tracker = MessageAttemptTracker(
            ttl_seconds=self._MESSAGE_ATTEMPT_TTL_SECONDS,
            max_entries=self._MESSAGE_ATTEMPT_MAX_ENTRIES,
            prune_interval_seconds=self._MESSAGE_ATTEMPT_PRUNE_INTERVAL_SECONDS,
        )
        self._windowed_error_logger = WindowedErrorLogger(
            window_seconds=self._ERROR_LOG_WINDOW_SECONDS,
            burst_limit=self._ERROR_LOG_BURST_LIMIT,
        )
        self._message_processor = WorkerMessageProcessor(
            consumer=self._consumer,
            handlers=self._handlers,
            default_handler=self._default_handler,
            error_handler=self._error_handler,
            ack_on_error=self._ack_on_error,
            ack_unknown_task=self._ack_unknown_task,
            delete_after_ack=self._delete_after_ack,
            max_retries=self._max_retries,
            dead_letter_handler=self._dead_letter_handler,
            stats=self._stats,
            increase_message_attempt=self._increase_message_attempt,
            clear_message_attempt=self._clear_message_attempt,
            log_exception_with_window=self._log_exception_with_window,
        )

    @property
    def stats(self) -> WorkerStats:
        """返回 Worker 当前的累计指标副本。"""
        return WorkerStats(
            total=self._stats.total,
            succeeded=self._stats.succeeded,
            failed=self._stats.failed,
            retried=self._stats.retried,
        )

    def register_handler(self, task_type: str | None, handler: WorkerHandler) -> None:
        """动态注册或覆盖 `task_type` 对应的处理函数。"""
        self._handlers[task_type] = handler

    def request_shutdown(self) -> None:
        """对外暴露的停机信号，常用于接收 SIGTERM 后的优雅退出。"""
        self._stop_event.set()

    async def run(self) -> None:
        """启动 Worker 主循环，直到调用者触发 shutdown。"""
        logger.info("Redis 流处理器启动，等待 Redis Streams 消息")
        try:
            while not self._stop_event.is_set():
                self._maybe_prune_message_attempts()
                messages = await self._safe_poll()
                if messages:
                    for message in messages:
                        if self._stop_event.is_set():
                            break
                        await self._submit_message(message)
                    continue

                await self._maybe_claim_idle()
                if self._idle_sleep:
                    await asyncio.sleep(self._idle_sleep)
        except asyncio.CancelledError:
            logger.warning("Redis 流处理器收到取消信号，准备退出")
            raise
        finally:
            await self._wait_for_tasks()
            logger.info(
                "Redis 流处理器已停止，处理总数={} 成功={} 失败={} 重试={}",
                self._stats.total,
                self._stats.succeeded,
                self._stats.failed,
                self._stats.retried,
            )

    async def _safe_poll(self) -> list[StreamMessage]:
        """包装 Consumer.poll，避免 Redis 暂时不可用导致主循环崩溃。"""
        try:
            return await self._consumer.poll()
        except asyncio.CancelledError:
            raise
        except _RECOVERABLE_STREAM_INFRA_ERRORS as exc:
            logger.error(
                "从 Redis Streams 拉取消息失败，将在短暂等待后重试 error_type={}",
                exc.__class__.__name__,
            )
            await asyncio.sleep(self._idle_sleep or 0.1)
            return []

    async def _submit_message(self, message: StreamMessage) -> None:
        """将消息提交到并发执行池。"""
        await self._semaphore.acquire()
        task = asyncio.create_task(self._handle_message(message))
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        """任务回调：释放信号量并捕获未处理异常。"""
        self._tasks.discard(task)
        self._semaphore.release()
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except BaseException as exc:
            if is_fatal_base_exception(exc):
                raise
            logger.error(
                "消息处理子任务执行失败 error_type={}",
                exc.__class__.__name__,
            )

    async def _handle_message(self, message: StreamMessage) -> None:
        """处理单条消息，委托给消息处理编排器。"""
        await self._message_processor.handle_message(message)

    async def _maybe_claim_idle(self) -> None:
        """认领 pending 超时消息，避免 Worker 异常退出后任务长期卡住。"""
        if self._claim_idle_ms is None:
            return
        now = time.monotonic()
        if now - self._last_claim_ts < self._claim_idle_interval:
            return

        self._last_claim_ts = now
        try:
            claimed, next_start = await self._consumer.claim_idle(
                min_idle_ms=self._claim_idle_ms,
                count=self._claim_idle_count,
                start=self._claim_idle_start,
            )
        except asyncio.CancelledError:
            raise
        except _RECOVERABLE_STREAM_INFRA_ERRORS as exc:
            logger.error(
                "认领 idle 消息失败，将在下一轮重试 error_type={}",
                exc.__class__.__name__,
            )
            return

        self._claim_idle_start = next_start or "0-0"
        if not claimed:
            return

        logger.info("认领 {} 条待处理消息（pending）准备重试", len(claimed))
        for message in claimed:
            if self._stop_event.is_set():
                break
            await self._submit_message(message)

    async def _wait_for_tasks(self) -> None:
        """等待所有并发任务结束，确保优雅退出。"""
        if not self._tasks:
            return
        await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        self._tasks.clear()

    def _increase_message_attempt(self, message_id: str) -> int:
        return self._message_attempt_tracker.increase(message_id)

    def _clear_message_attempt(self, message_id: str) -> None:
        self._message_attempt_tracker.clear(message_id)

    def _log_exception_with_window(
        self,
        key: str,
        exception: BaseException,
        message: str,
        *args: object,
    ) -> None:
        """在时间窗口内限制同类异常日志数量，超额日志做聚合计数。"""
        if (
            self._windowed_error_logger.window_seconds != self._ERROR_LOG_WINDOW_SECONDS
            or self._windowed_error_logger.burst_limit != self._ERROR_LOG_BURST_LIMIT
        ):
            self._windowed_error_logger = WindowedErrorLogger(
                window_seconds=self._ERROR_LOG_WINDOW_SECONDS,
                burst_limit=self._ERROR_LOG_BURST_LIMIT,
            )
        self._windowed_error_logger.log_exception(
            key,
            exception,
            message,
            *args,
            log=logger,
        )

    def _maybe_prune_message_attempts(self) -> None:
        """定期清理消息重试状态，防止长期 pending 导致内存持续增长。"""
        removed = self._message_attempt_tracker.maybe_prune()
        if removed > 0:
            logger.debug(
                "已清理消息重试状态：removed={} remaining={}",
                removed,
                self._message_attempt_tracker.size,
            )


__all__ = ["WorkerResult", "WorkerStats", "RedisWorker"]
