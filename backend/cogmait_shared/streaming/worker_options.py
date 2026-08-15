"""RedisWorker 配置项与校验。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

DEFAULT_WORKER_MAX_RETRIES = 3


@dataclass(slots=True, frozen=True)
class WorkerOptions:
    """RedisWorker 运行配置。"""

    max_concurrency: int = 1
    idle_sleep: float = 0.5
    ack_on_error: bool = False
    ack_unknown_task: bool = False
    delete_after_ack: bool = False
    max_retries: int | None = DEFAULT_WORKER_MAX_RETRIES
    dead_letter_handler: Callable[..., Awaitable[None] | None] | None = None
    claim_idle_ms: int | None = None
    claim_idle_interval: float = 60.0
    claim_idle_count: int = 20

    def validate(self) -> None:
        _validate_option_types(
            max_concurrency=self.max_concurrency,
            idle_sleep=self.idle_sleep,
            ack_on_error=self.ack_on_error,
            ack_unknown_task=self.ack_unknown_task,
            delete_after_ack=self.delete_after_ack,
            max_retries=self.max_retries,
            dead_letter_handler=self.dead_letter_handler,
            claim_idle_ms=self.claim_idle_ms,
            claim_idle_interval=self.claim_idle_interval,
            claim_idle_count=self.claim_idle_count,
        )
        _validate_option_ranges(
            max_concurrency=self.max_concurrency,
            idle_sleep=self.idle_sleep,
            max_retries=self.max_retries,
            claim_idle_ms=self.claim_idle_ms,
            claim_idle_interval=self.claim_idle_interval,
            claim_idle_count=self.claim_idle_count,
        )


def _validate_option_types(
    *,
    max_concurrency: int,
    idle_sleep: float,
    ack_on_error: bool,
    ack_unknown_task: bool,
    delete_after_ack: bool,
    max_retries: int | None,
    dead_letter_handler: Callable[..., Awaitable[None] | None] | None,
    claim_idle_ms: int | None,
    claim_idle_interval: float,
    claim_idle_count: int,
) -> None:
    _validate_int_option(
        max_concurrency,
        nullable=False,
        message="max_concurrency must be an integer",
    )
    _validate_number_option(
        idle_sleep,
        message="idle_sleep must be a number",
    )
    _validate_bool_option(ack_on_error, field_name="ack_on_error")
    _validate_bool_option(ack_unknown_task, field_name="ack_unknown_task")
    _validate_bool_option(delete_after_ack, field_name="delete_after_ack")
    _validate_int_option(
        max_retries,
        nullable=True,
        message="max_retries must be an integer when provided",
    )
    _validate_callable_option(
        dead_letter_handler,
        field_name="dead_letter_handler",
    )
    _validate_int_option(
        claim_idle_ms,
        nullable=True,
        message="claim_idle_ms must be an integer when provided",
    )
    _validate_number_option(
        claim_idle_interval,
        message="claim_idle_interval must be a number",
    )
    _validate_int_option(
        claim_idle_count,
        nullable=False,
        message="claim_idle_count must be an integer",
    )


def _validate_option_ranges(
    *,
    max_concurrency: int,
    idle_sleep: float,
    max_retries: int | None,
    claim_idle_ms: int | None,
    claim_idle_interval: float,
    claim_idle_count: int,
) -> None:
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be >= 1")
    if idle_sleep < 0:
        raise ValueError("idle_sleep must be >= 0")
    if max_retries is not None and max_retries < 1:
        raise ValueError("max_retries must be >= 1")
    if claim_idle_ms is not None and claim_idle_ms <= 0:
        raise ValueError("claim_idle_ms must be > 0")
    if claim_idle_interval < 0:
        raise ValueError("claim_idle_interval must be >= 0")
    if claim_idle_count < 1:
        raise ValueError("claim_idle_count must be >= 1")


def _validate_bool_option(value: object, *, field_name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")


def _validate_number_option(value: object, *, message: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(message)


def _validate_int_option(
    value: object,
    *,
    nullable: bool,
    message: str,
) -> None:
    if value is None:
        if nullable:
            return
        raise ValueError(message)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(message)


def _validate_callable_option(value: object, *, field_name: str) -> None:
    if value is not None and not callable(value):
        raise ValueError(f"{field_name} must be callable when provided")


__all__ = ["DEFAULT_WORKER_MAX_RETRIES", "WorkerOptions"]
