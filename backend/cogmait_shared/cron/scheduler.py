"""APScheduler(AsyncIO) Cron 调度封装（带 Redis 触发点锁）。"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from traceback import format_tb
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
    JobExecutionEvent,
)
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.executors.base import run_job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.util import iscoroutinefunction_partial
from redis.exceptions import RedisError

from ..cache import CacheOps
from ..core.coercion import parse_strict_bool
from ..observability.logging import logger
from .models import CronJobConfig

_RECOVERABLE_SCHEDULER_INFRA_ERRORS = (
    RedisError,
    ConnectionError,
    TimeoutError,
    OSError,
)
_FATAL_BASE_EXCEPTIONS = (KeyboardInterrupt, SystemExit)
_DEFAULT_JOBSTORE_ALIAS = "default"
_DEFAULT_EXECUTOR_LOGGER_NAME = "apscheduler.executors.default"


@dataclass(slots=True)
class CronSchedulerSettings:
    enabled: bool = True
    timezone: str = "Asia/Shanghai"
    lock_key_prefix: str = "cron:lock:"

    def __post_init__(self) -> None:
        resolved_enabled = parse_strict_bool(self.enabled)
        if resolved_enabled is None:
            raise ValueError("enabled 必须为布尔值")
        self.enabled = resolved_enabled

        if not isinstance(self.lock_key_prefix, str):
            raise ValueError("lock_key_prefix 必须为字符串")
        if not isinstance(self.timezone, str):
            raise ValueError("timezone 必须为字符串")
        normalized_prefix = self.lock_key_prefix.strip()
        if not normalized_prefix:
            raise ValueError("lock_key_prefix 不能为空")
        normalized_timezone = self.timezone.strip()
        if not normalized_timezone:
            raise ValueError("timezone 不能为空")
        ZoneInfo(normalized_timezone)
        self.lock_key_prefix = normalized_prefix
        self.timezone = normalized_timezone


class CronScheduler:
    """Cron 调度器：触发 job，并使用 Redis 触发点锁避免多副本重复执行。"""

    def __init__(
        self,
        *,
        cache: CacheOps,
        settings: CronSchedulerSettings | None = None,
    ) -> None:
        self._cache = cache
        self._settings = settings or CronSchedulerSettings()
        self._scheduler = AsyncIOScheduler(
            executors={"default": _ScheduledRunTimeAsyncIOExecutor()},
            timezone=self._settings.timezone,
        )
        self._stop_event = asyncio.Event()

    def register_jobs(self, jobs: list[CronJobConfig]) -> None:
        for job in jobs:
            if not job.enabled:
                logger.info("cron job disabled: {}", job.job_id)
                continue
            trigger = _parse_cron(job.cron, timezone=self._settings.timezone)
            self._scheduler.add_job(
                self._run_job,
                trigger=trigger,
                id=job.job_id,
                name=job.job_id,
                kwargs={"job": job},
                misfire_grace_time=job.misfire_grace_time,
                coalesce=job.coalesce,
                max_instances=job.max_instances,
            )
            logger.info("cron job registered: {} cron={}", job.job_id, job.cron)

    async def run_forever(self) -> None:
        if not self._settings.enabled:
            logger.warning("CronScheduler disabled, exit")
            return
        self._scheduler.start()
        logger.info("CronScheduler started timezone={}", self._settings.timezone)
        try:
            await self._stop_event.wait()
        finally:
            if self._scheduler.running:
                self._scheduler.shutdown(wait=False)

    def request_shutdown(self) -> None:
        self._stop_event.set()

    async def _run_job(
        self, *, job: CronJobConfig, scheduled_run_time: datetime | None = None
    ) -> None:
        scheduled_at = self._resolve_scheduled_at(
            job=job,
            scheduled_run_time=scheduled_run_time,
        )
        lock_key = self._build_lock_key(job=job, scheduled_at=scheduled_at)
        token = uuid4().hex
        if not await self._acquire_lock(
            job=job,
            lock_key=lock_key,
            token=token,
            scheduled_at=scheduled_at,
        ):
            return

        started_at = datetime.now(tz=scheduled_at.tzinfo)
        try:
            logger.info("cron start: job={} scheduled_at={}", job.job_id, scheduled_at.isoformat())
            await job.func(scheduled_at=scheduled_at)
            duration_ms = int(
                (datetime.now(tz=scheduled_at.tzinfo) - started_at).total_seconds() * 1000
            )
            logger.info(
                "cron done: job={} scheduled_at={} duration_ms={}",
                job.job_id,
                scheduled_at.isoformat(),
                duration_ms,
            )
        except asyncio.CancelledError:
            self._log_cancelled(job=job, scheduled_at=scheduled_at)
            raise
        except BaseException as exc:
            if isinstance(exc, _FATAL_BASE_EXCEPTIONS):
                raise
            self._log_failed(job=job, scheduled_at=scheduled_at, exc=exc)
            raise
        finally:
            try:
                released = await self._cache.release_lock(lock_key, token)
                if not released:
                    logger.warning(
                        "cron release lock skipped (token mismatch): job={} scheduled_at={} key={}",
                        job.job_id,
                        scheduled_at.isoformat(),
                        lock_key,
                    )
            except _RECOVERABLE_SCHEDULER_INFRA_ERRORS as exc:
                logger.error(
                    "cron release lock failed: job={} scheduled_at={} key={} error_type={}",
                    job.job_id,
                    scheduled_at.isoformat(),
                    lock_key,
                    exc.__class__.__name__,
                )

    def _resolve_scheduled_at(
        self,
        *,
        job: CronJobConfig,
        scheduled_run_time: datetime | None,
    ) -> datetime:
        return _bucket_for_lock(
            cron=job.cron,
            timezone=self._settings.timezone,
            scheduled_run_time=scheduled_run_time,
        )

    def _build_lock_key(self, *, job: CronJobConfig, scheduled_at: datetime) -> str:
        return _lock_key(
            prefix=self._settings.lock_key_prefix,
            job_id=job.job_id,
            scheduled_at=scheduled_at,
            cron=job.cron,
        )

    async def _acquire_lock(
        self,
        *,
        job: CronJobConfig,
        lock_key: str,
        token: str,
        scheduled_at: datetime,
    ) -> bool:
        acquired = await self._cache.acquire_lock(
            lock_key,
            token,
            ttl_seconds=job.lock_ttl_seconds,
        )
        if acquired:
            return True
        logger.info(
            "cron skip (lock busy): job={} scheduled_at={} key={}",
            job.job_id,
            scheduled_at.isoformat(),
            lock_key,
        )
        return False

    @staticmethod
    def _log_cancelled(*, job: CronJobConfig, scheduled_at: datetime) -> None:
        logger.warning(
            "cron cancelled: job={} scheduled_at={}",
            job.job_id,
            scheduled_at.isoformat(),
        )

    @staticmethod
    def _log_failed(*, job: CronJobConfig, scheduled_at: datetime, exc: BaseException) -> None:
        logger.error(
            "cron failed: job={} scheduled_at={} error_type={}",
            job.job_id,
            scheduled_at.isoformat(),
            exc.__class__.__name__,
        )


def _parse_cron(expr: str, *, timezone: str) -> CronTrigger:
    parts = _split_cron_expr(expr)
    if len(parts) == 5:
        minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=timezone,
        )
    if len(parts) == 6:
        second, minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            second=second,
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=timezone,
        )
    raise ValueError(f"无效的 cron 表达式：{expr}（需 5 或 6 个字段）")


def _bucket_for_lock(*, cron: str, timezone: str, scheduled_run_time: datetime | None) -> datetime:
    tz = ZoneInfo(timezone)
    base = scheduled_run_time.astimezone(tz) if scheduled_run_time else datetime.now(tz=tz)
    parts = _split_cron_expr(cron)
    if len(parts) == 6:
        return base.replace(microsecond=0)
    return base.replace(second=0, microsecond=0)


def _lock_key(*, prefix: str, job_id: str, scheduled_at: datetime, cron: str) -> str:
    parts = _split_cron_expr(cron)
    suffix = scheduled_at.strftime("%Y%m%d%H%M%S" if len(parts) == 6 else "%Y%m%d%H%M")
    return f"{prefix}{job_id}:{suffix}"


def _split_cron_expr(expr: str) -> list[str]:
    return [item.strip() for item in expr.split() if item.strip()]


class _ScheduledRunTimeAsyncIOExecutor(AsyncIOExecutor):
    def _do_submit_job(self, job: Any, run_times: list[datetime]) -> None:
        def callback(f) -> None:
            self._pending_futures.discard(f)
            try:
                events = f.result()
            except BaseException:
                self._run_job_error(job.id, *sys.exc_info()[1:])
            else:
                self._run_job_success(job.id, events)

        if iscoroutinefunction_partial(job.func):
            coro = _run_coroutine_job_with_scheduled_time(
                job,
                _DEFAULT_JOBSTORE_ALIAS,
                run_times,
                _DEFAULT_EXECUTOR_LOGGER_NAME,
            )
            future = self._eventloop.create_task(coro)
        else:
            future = self._eventloop.run_in_executor(
                None,
                run_job,
                job,
                _DEFAULT_JOBSTORE_ALIAS,
                run_times,
                _DEFAULT_EXECUTOR_LOGGER_NAME,
            )

        future.add_done_callback(callback)
        self._pending_futures.add(future)


async def _run_coroutine_job_with_scheduled_time(
    job: Any,
    jobstore_alias: str,
    run_times: list[datetime],
    logger_name: str,
) -> list[JobExecutionEvent]:
    events: list[JobExecutionEvent] = []
    scheduler_logger = logging.getLogger(logger_name)
    for run_time in run_times:
        if job.misfire_grace_time is not None:
            difference = datetime.now(UTC) - run_time
            grace_time = timedelta(seconds=job.misfire_grace_time)
            if difference > grace_time:
                events.append(JobExecutionEvent(EVENT_JOB_MISSED, job.id, jobstore_alias, run_time))
                scheduler_logger.warning('Run time of job "%s" was missed by %s', job, difference)
                continue

        scheduler_logger.info('Running job "%s" (scheduled at %s)', job, run_time)
        try:
            kwargs = dict(job.kwargs)
            kwargs["scheduled_run_time"] = run_time
            retval = await job.func(*job.args, **kwargs)
        except asyncio.CancelledError:
            scheduler_logger.warning('Job "%s" was cancelled', job)
            raise
        except _FATAL_BASE_EXCEPTIONS:
            raise
        except BaseException as exc:
            formatted_tb = "".join(format_tb(exc.__traceback__))
            events.append(
                JobExecutionEvent(
                    EVENT_JOB_ERROR,
                    job.id,
                    jobstore_alias,
                    run_time,
                    exception=exc,
                    traceback=formatted_tb,
                )
            )
            scheduler_logger.error(
                'Job "%s" raised an exception error_type=%s',
                job,
                exc.__class__.__name__,
            )
        else:
            events.append(
                JobExecutionEvent(
                    EVENT_JOB_EXECUTED,
                    job.id,
                    jobstore_alias,
                    run_time,
                    retval=retval,
                )
            )
            scheduler_logger.info('Job "%s" executed successfully', job)

    return events
