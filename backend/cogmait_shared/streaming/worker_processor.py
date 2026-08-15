"""RedisWorker 消息处理编排器。"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, cast

from redis.exceptions import RedisError

from cogmait_shared.observability.logging import logger, request_id_context

from .models import StreamMessage, StreamMessageDecodeError

_RECOVERABLE_STREAM_INFRA_ERRORS = (
    RedisError,
    ConnectionError,
    TimeoutError,
    OSError,
)
_FATAL_BASE_EXCEPTIONS = (KeyboardInterrupt, SystemExit)


class _MutableWorkerStats(Protocol):
    total: int
    succeeded: int
    failed: int
    retried: int


class _ConsumerAckDelete(Protocol):
    async def ack(self, *message_ids: str) -> int: ...

    async def delete(self, *message_ids: str) -> int: ...


class _WorkerResultLike(Protocol):
    ack: bool
    delete: bool


WorkerHandler = Callable[
    [StreamMessage],
    Awaitable[_WorkerResultLike | None] | _WorkerResultLike | None,
]
WorkerErrorHandler = Callable[
    [StreamMessage, BaseException],
    Awaitable[_WorkerResultLike | None] | _WorkerResultLike | None,
]
DeadLetterHandler = Callable[
    [StreamMessage, int, str],
    Awaitable[None] | None,
]


def is_fatal_base_exception(exc: BaseException) -> bool:
    return isinstance(exc, _FATAL_BASE_EXCEPTIONS)


class WorkerMessageProcessor:
    """负责单条消息的处理、异常收敛与 ack/delete 决策。"""

    def __init__(
        self,
        *,
        consumer: _ConsumerAckDelete,
        handlers: Mapping[str | None, WorkerHandler],
        default_handler: WorkerHandler | None,
        error_handler: WorkerErrorHandler | None,
        ack_on_error: bool,
        ack_unknown_task: bool,
        delete_after_ack: bool,
        max_retries: int | None,
        dead_letter_handler: DeadLetterHandler | None,
        stats: _MutableWorkerStats,
        increase_message_attempt: Callable[[str], int],
        clear_message_attempt: Callable[[str], None],
        log_exception_with_window: Callable[..., None],
    ) -> None:
        self._consumer = consumer
        self._handlers = handlers
        self._default_handler = default_handler
        self._error_handler = error_handler
        self._ack_on_error = ack_on_error
        self._ack_unknown_task = ack_unknown_task
        self._delete_after_ack = delete_after_ack
        self._max_retries = max_retries
        self._dead_letter_handler = dead_letter_handler
        self._stats = stats
        self._increase_message_attempt = increase_message_attempt
        self._clear_message_attempt = clear_message_attempt
        self._log_exception_with_window = log_exception_with_window

    async def handle_message(self, message: StreamMessage) -> None:
        """处理单条消息，包含 request_id 透传与 ack 控制。"""
        handler = self._handlers.get(message.task_type) or self._default_handler

        self._stats.total += 1
        current_attempt = self._increase_message_attempt(message.message_id)
        message.retry_count = max(current_attempt - 1, 0)
        if self._should_dead_letter(current_attempt):
            await self._handle_retry_exhausted_message(message, current_attempt)
            return

        if message.decode_error is not None:
            self._stats.failed += 1
            await self._handle_handler_error(
                message,
                StreamMessageDecodeError(message.decode_error),
            )
            return

        if handler is None:
            await self._handle_unknown_task(message)
            return

        with request_id_context(message.request_id):
            try:
                result = await self._invoke_handler(handler, message)
                await self._apply_result(message, result, from_error=False)
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                if is_fatal_base_exception(exc):
                    raise
                self._stats.failed += 1
                await self._handle_handler_error(message, exc)

    async def _handle_handler_error(self, message: StreamMessage, exc: BaseException) -> None:
        """处理 handler 异常，调用自定义 error_handler 或按策略决定 ack。"""
        logger.error(
            "处理消息 {} 时发生异常，task_type={} error_type={}",
            message.message_id,
            message.task_type,
            exc.__class__.__name__,
        )

        if self._error_handler:
            try:
                result = await self._maybe_await(self._error_handler(message, exc))
            except asyncio.CancelledError:
                raise
            except BaseException as handler_exc:
                if is_fatal_base_exception(handler_exc):
                    raise
                self._log_exception_with_window(
                    "error_handler_failed",
                    handler_exc,
                    "异常处理器内部再次抛出异常，消息将保持待处理状态（pending）",
                )
                self._stats.retried += 1
                return
        else:
            result = _StaticWorkerResult(ack=self._ack_on_error, delete=False)

        await self._apply_result(message, result, from_error=True)

    async def _apply_result(
        self,
        message: StreamMessage,
        result: _WorkerResultLike | None,
        *,
        from_error: bool,
    ) -> None:
        """根据 WorkerResult 执行 ack/delete，并更新统计。"""
        ack, delete = self._normalize_result(result)
        if ack:
            try:
                await self._ack_and_maybe_delete(
                    message.message_id,
                    delete=delete,
                )
            except asyncio.CancelledError:
                raise
            except _RECOVERABLE_STREAM_INFRA_ERRORS as ack_exc:
                self._log_exception_with_window(
                    "ack_failed",
                    ack_exc,
                    "确认消息失败，保持待处理状态（pending）：message_id={} task_type={}",
                    message.message_id,
                    message.task_type,
                )
                self._stats.retried += 1
                return
            if not from_error:
                self._stats.succeeded += 1
            self._clear_message_attempt(message.message_id)
            return
        self._stats.retried += 1

    async def _handle_unknown_task(self, message: StreamMessage) -> None:
        if self._ack_unknown_task:
            try:
                await self._ack_and_maybe_delete(
                    message.message_id,
                    delete=self._delete_after_ack,
                )
            except asyncio.CancelledError:
                raise
            except _RECOVERABLE_STREAM_INFRA_ERRORS as unknown_ack_exc:
                self._log_exception_with_window(
                    "ack_unknown_task_failed",
                    unknown_ack_exc,
                    (
                        "确认未知任务消息失败，保持待处理状态（pending）："
                        "message_id={} task_type={}"
                    ),
                    message.message_id,
                    message.task_type,
                )
                self._stats.retried += 1
                return
            self._clear_message_attempt(message.message_id)
            self._stats.succeeded += 1
            return
        self._stats.retried += 1
        logger.warning(
            "未找到 task_type={} 的 handler，消息保持待处理状态（pending）",
            message.task_type,
        )

    async def _ack_and_maybe_delete(self, message_id: str, *, delete: bool) -> None:
        await self._consumer.ack(message_id)
        if not delete:
            return
        try:
            await self._consumer.delete(message_id)
        except asyncio.CancelledError:
            raise
        except _RECOVERABLE_STREAM_INFRA_ERRORS as delete_exc:
            self._log_exception_with_window(
                "delete_acknowledged_message_failed",
                delete_exc,
                "删除已确认消息失败：message_id={}",
                message_id,
            )

    async def _invoke_handler(
        self,
        handler: WorkerHandler,
        message: StreamMessage,
    ) -> _WorkerResultLike | None:
        """统一处理同步/异步 handler 的返回值。"""
        result = handler(message)
        return await self._maybe_await(result)

    async def _maybe_await(
        self,
        result: _WorkerResultLike | None | Awaitable[_WorkerResultLike | None],
    ) -> _WorkerResultLike | None:
        """在运行时判断返回值是否 Awaitable。"""
        if inspect.isawaitable(result):
            return await cast(Awaitable[_WorkerResultLike | None], result)
        return cast(_WorkerResultLike | None, result)

    def _normalize_result(self, result: _WorkerResultLike | None) -> tuple[bool, bool]:
        """根据全局策略补齐 delete 标志。"""
        if result is None:
            ack = True
            delete = False
        else:
            ack = result.ack
            delete = result.delete
        delete = delete or (ack and self._delete_after_ack)
        return ack, delete

    def _should_dead_letter(self, current_attempt: int) -> bool:
        return self._max_retries is not None and current_attempt > self._max_retries

    async def _handle_retry_exhausted_message(self, message: StreamMessage, attempt: int) -> None:
        reason = "max_retries_exceeded"
        self._stats.failed += 1
        logger.warning(
            (
                "消息超过最大重试次数，转为死信并收敛："
                "message_id={} task_type={} attempt={} max_retries={}"
            ),
            message.message_id,
            message.task_type,
            attempt,
            self._max_retries,
        )
        if self._dead_letter_handler is not None:
            # 死信回调是尽力通知；回调失败仍确认消息，避免无效消息反复占用 pending。
            try:
                await self._maybe_await(self._dead_letter_handler(message, attempt, reason))
            except asyncio.CancelledError:
                raise
            except BaseException as dead_letter_exc:
                if is_fatal_base_exception(dead_letter_exc):
                    raise
                logger.error(
                    "死信处理回调执行失败：message_id={} task_type={} error_type={}",
                    message.message_id,
                    message.task_type,
                    dead_letter_exc.__class__.__name__,
                )

        try:
            await self._ack_and_maybe_delete(
                message.message_id,
                delete=self._delete_after_ack,
            )
            self._clear_message_attempt(message.message_id)
        except asyncio.CancelledError:
            raise
        except _RECOVERABLE_STREAM_INFRA_ERRORS as exc:
            logger.error(
                "死信消息确认失败，保持待处理状态（pending）：message_id={} task_type={} "
                "error_type={}",
                message.message_id,
                message.task_type,
                exc.__class__.__name__,
            )
            self._stats.retried += 1


class _StaticWorkerResult:
    """用于错误兜底路径的最小结果对象。"""

    def __init__(self, *, ack: bool, delete: bool) -> None:
        self.ack = ack
        self.delete = delete


__all__ = ["WorkerMessageProcessor", "is_fatal_base_exception"]
