"""跨服务复用的 Cron 调度工具。

提供：
- Cron 表达式解析（支持 5 段分钟级与 6 段秒级）
- 触发点锁 key 生成（job_id + scheduled_at bucket）
- APScheduler(AsyncIO) 简化封装（配合 Redis 锁实现多副本去重）
"""

from .models import CronJobConfig
from .runner import (
    CronSchedulerFactory,
    CronSchedulerLike,
    run_registered_cron_scheduler,
    run_service_cron_scheduler,
)
from .scheduler import CronScheduler, CronSchedulerSettings

__all__ = [
    "CronJobConfig",
    "CronScheduler",
    "CronSchedulerFactory",
    "CronSchedulerLike",
    "CronSchedulerSettings",
    "run_registered_cron_scheduler",
    "run_service_cron_scheduler",
]
