"""Cron 调度相关类型。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..core.coercion import parse_required_int, parse_strict_bool

CronJobFunc = Callable[..., Awaitable[None]]


@dataclass(slots=True)
class CronJobConfig:
    job_id: str
    cron: str
    func: CronJobFunc
    enabled: bool = True
    lock_ttl_seconds: int = 300
    misfire_grace_time: int = 300
    coalesce: bool = True
    max_instances: int = 1

    def __post_init__(self) -> None:
        self._normalize_identity_fields()
        self._normalize_callable()
        self._normalize_switches()
        self._normalize_limits()

    def _normalize_identity_fields(self) -> None:
        if not isinstance(self.job_id, str):
            raise ValueError("job_id 必须为字符串")
        if not isinstance(self.cron, str):
            raise ValueError("cron 必须为字符串")
        self.job_id = self.job_id.strip()
        self.cron = self.cron.strip()
        if not self.job_id:
            raise ValueError("job_id 不能为空")
        if not self.cron:
            raise ValueError("cron 不能为空")

    def _normalize_callable(self) -> None:
        if not callable(self.func):
            raise ValueError("func 必须为可调用对象")

    def _normalize_switches(self) -> None:
        resolved_enabled = parse_strict_bool(self.enabled)
        resolved_coalesce = parse_strict_bool(self.coalesce)
        if resolved_enabled is None:
            raise ValueError("enabled 必须为布尔值")
        if resolved_coalesce is None:
            raise ValueError("coalesce 必须为布尔值")
        self.enabled = resolved_enabled
        self.coalesce = resolved_coalesce

    def _normalize_limits(self) -> None:
        self.lock_ttl_seconds = parse_required_int(
            self.lock_ttl_seconds,
            field_name="lock_ttl_seconds",
        )
        self.misfire_grace_time = parse_required_int(
            self.misfire_grace_time,
            field_name="misfire_grace_time",
        )
        self.max_instances = parse_required_int(
            self.max_instances,
            field_name="max_instances",
        )

        if self.lock_ttl_seconds <= 0:
            raise ValueError("lock_ttl_seconds 必须大于 0")
        if self.misfire_grace_time < 0:
            raise ValueError("misfire_grace_time 必须大于等于 0")
        if self.max_instances < 1:
            raise ValueError("max_instances 必须大于等于 1")
