"""Cron 调度入口公共运行流程。"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable
from contextlib import suppress
from typing import Any, Protocol

from cogmait_shared.cache import CacheOps, CacheRepository, CacheService
from cogmait_shared.observability.logging import logger

from .models import CronJobConfig
from .scheduler import CronScheduler, CronSchedulerSettings


class CronSchedulerLike(Protocol):
    def register_jobs(self, jobs: list[CronJobConfig]) -> None: ...

    def request_shutdown(self) -> None: ...

    async def run_forever(self) -> None: ...


class CronSchedulerFactory(Protocol):
    def __call__(
        self,
        *,
        cache: CacheOps,
        settings: CronSchedulerSettings,
    ) -> CronSchedulerLike: ...


async def run_registered_cron_scheduler(
    *,
    enabled: bool,
    timezone: str,
    jobs: list[CronJobConfig],
    cache_factory: Callable[[], CacheOps],
    scheduler_cls: CronSchedulerFactory = CronScheduler,
    settings_cls: Callable[..., CronSchedulerSettings] = CronSchedulerSettings,
    loop_factory: Callable[[], asyncio.AbstractEventLoop] = asyncio.get_running_loop,
    disabled_message: str = "cron_scheduler disabled (CRON_ENABLED=0), exit",
) -> None:
    """注册 Cron 任务、绑定退出信号并常驻运行。"""

    if not enabled:
        logger.warning(disabled_message)
        return

    cache = cache_factory()
    scheduler = scheduler_cls(
        cache=cache,
        settings=settings_cls(
            enabled=True,
            timezone=timezone,
        ),
    )
    scheduler.register_jobs(jobs)

    loop = loop_factory()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, scheduler.request_shutdown)

    await scheduler.run_forever()


async def run_service_cron_scheduler(
    *,
    enabled: bool,
    timezone: str,
    jobs: list[CronJobConfig],
    redis_client_factory: Callable[[], Any],
    redis_key_prefix: str,
    cache_repository_cls: Callable[..., Any] = CacheRepository,
    cache_service_cls: Callable[..., CacheOps] = CacheService,
    scheduler_cls: CronSchedulerFactory = CronScheduler,
    settings_cls: Callable[..., CronSchedulerSettings] = CronSchedulerSettings,
    loop_factory: Callable[[], asyncio.AbstractEventLoop] = asyncio.get_running_loop,
) -> None:
    """使用服务本地 Redis 配置启动已注册的 Cron 任务。"""

    await run_registered_cron_scheduler(
        enabled=enabled,
        timezone=timezone,
        jobs=jobs,
        cache_factory=lambda: cache_service_cls(
            cache_repository_cls(redis_client_factory(), key_prefix=redis_key_prefix)
        ),
        scheduler_cls=scheduler_cls,
        settings_cls=settings_cls,
        loop_factory=loop_factory,
    )


__all__ = [
    "CronSchedulerFactory",
    "CronSchedulerLike",
    "run_registered_cron_scheduler",
    "run_service_cron_scheduler",
]
