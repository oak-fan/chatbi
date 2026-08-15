"""RedisWorker 运行时辅助组件。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class _ErrorLogWindowState:
    """异常日志窗口状态。"""

    window_start: float
    emitted: int = 0
    suppressed: int = 0


class WindowedErrorLogger:
    """在时间窗口内限制同类错误日志的输出频率。"""

    def __init__(self, *, window_seconds: float, burst_limit: int) -> None:
        self._window_seconds = window_seconds
        self._burst_limit = burst_limit
        self._windows: dict[str, _ErrorLogWindowState] = {}

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    @property
    def burst_limit(self) -> int:
        return self._burst_limit

    def log_exception(
        self,
        key: str,
        exception: BaseException,
        message: str,
        *args: object,
        log: Any,
    ) -> None:
        now = time.monotonic()
        state = self._windows.get(key)
        if state is None or (now - state.window_start) >= self._window_seconds:
            if state is not None and state.suppressed:
                log.warning(
                    "错误日志聚合：key={} window={}s suppressed={}",
                    key,
                    self._window_seconds,
                    state.suppressed,
                )
            state = _ErrorLogWindowState(window_start=now)
            self._windows[key] = state

        if state.emitted >= self._burst_limit:
            state.suppressed += 1
            return

        state.emitted += 1
        log.error(
            f"{message} error_type={{}}",
            *args,
            exception.__class__.__name__,
        )


class MessageAttemptTracker:
    """消息重试状态跟踪器，负责计数与定期清理。"""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_entries: int,
        prune_interval_seconds: float,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._prune_interval_seconds = prune_interval_seconds
        self._attempts: dict[str, int] = {}
        self._last_seen: dict[str, float] = {}
        self._last_prune_ts = 0.0

    @property
    def size(self) -> int:
        return len(self._attempts)

    def increase(self, message_id: str) -> int:
        current_attempt = self._attempts.get(message_id, 0) + 1
        self._attempts[message_id] = current_attempt
        self._last_seen[message_id] = time.monotonic()
        return current_attempt

    def clear(self, message_id: str) -> None:
        self._attempts.pop(message_id, None)
        self._last_seen.pop(message_id, None)

    def maybe_prune(self) -> int:
        now = time.monotonic()
        if now - self._last_prune_ts < self._prune_interval_seconds:
            return 0
        self._last_prune_ts = now

        removed = 0
        stale_before = now - self._ttl_seconds
        stale_message_ids = [
            message_id
            for message_id, last_seen in self._last_seen.items()
            if last_seen < stale_before
        ]
        for message_id in stale_message_ids:
            self.clear(message_id)
            removed += 1

        overflow = len(self._attempts) - self._max_entries
        if overflow > 0:
            oldest_message_ids = sorted(
                self._last_seen.items(),
                key=lambda item: item[1],
            )[:overflow]
            for message_id, _ in oldest_message_ids:
                self.clear(message_id)
                removed += 1
        return removed


__all__ = ["MessageAttemptTracker", "WindowedErrorLogger"]
