from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from secrets import randbits
from threading import Lock
from time import time
from uuid import UUID

from cogmait_shared.observability.logging import logger

from .datetime_utils import APP_TIMEZONE, now_local

DEFAULT_TIMESTAMP_BITS = 41
DEFAULT_DATACENTER_BITS = 5
DEFAULT_WORKER_BITS = 5
DEFAULT_SEQUENCE_BITS = 12
DEFAULT_EPOCH = datetime(2024, 1, 1, tzinfo=APP_TIMEZONE)

UUIDV7_VERSION_BITS = 0x7000
UUID_VARIANT_BITS = 0x80
UUID_TIMESTAMP_MASK = (1 << 60) - 1


def _current_time_millis() -> int:
    return int(time() * 1000)


class ClockMovedBackwardsError(RuntimeError):
    """Raised when the system clock moves backwards."""


def _datetime_to_millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)


@dataclass(slots=True)
class SnowflakeConfig:
    datacenter_bits: int = DEFAULT_DATACENTER_BITS
    worker_bits: int = DEFAULT_WORKER_BITS
    sequence_bits: int = DEFAULT_SEQUENCE_BITS
    timestamp_bits: int = DEFAULT_TIMESTAMP_BITS
    epoch: int = _datetime_to_millis(DEFAULT_EPOCH)


class SnowflakeGenerator:
    def __init__(
        self,
        *,
        datacenter_id: int,
        worker_id: int,
        config: SnowflakeConfig | None = None,
        time_provider: Callable[[], int] | None = None,
    ) -> None:
        self.config = config or SnowflakeConfig()
        self._time_provider = time_provider or self._current_time_millis
        self._lock = Lock()
        self.last_timestamp = -1
        self.sequence = 0

        bits_sum = (
            self.config.timestamp_bits
            + self.config.datacenter_bits
            + self.config.worker_bits
            + self.config.sequence_bits
        )
        if bits_sum > 63:
            raise ValueError("Snowflake layout must fit in signed 64-bit integer")

        self.max_datacenter_id = (1 << self.config.datacenter_bits) - 1
        self.max_worker_id = (1 << self.config.worker_bits) - 1
        self.max_sequence = (1 << self.config.sequence_bits) - 1

        if not 0 <= datacenter_id <= self.max_datacenter_id:
            raise ValueError("datacenter_id out of range")
        if not 0 <= worker_id <= self.max_worker_id:
            raise ValueError("worker_id out of range")

        self.datacenter_id = datacenter_id
        self.worker_id = worker_id

        self.timestamp_shift = (
            self.config.datacenter_bits + self.config.worker_bits + self.config.sequence_bits
        )
        self.datacenter_shift = self.config.worker_bits + self.config.sequence_bits
        self.worker_shift = self.config.sequence_bits

    def _current_time_millis(self) -> int:
        return int(now_local().timestamp() * 1000)

    def _wait_next_millis(self, last_timestamp: int) -> int:
        timestamp = self._time_provider()
        while timestamp <= last_timestamp:
            timestamp = self._time_provider()
        return timestamp

    def generate_id(self) -> int:
        with self._lock:
            timestamp = self._time_provider()

            if timestamp < self.last_timestamp:
                raise ClockMovedBackwardsError("System clock moved backwards")

            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & self.max_sequence
                if self.sequence == 0:
                    timestamp = self._wait_next_millis(self.last_timestamp)
            else:
                self.sequence = 0

            self.last_timestamp = timestamp

            return ((timestamp - self.config.epoch) << self.timestamp_shift) | (
                (self.datacenter_id << self.datacenter_shift)
                | (self.worker_id << self.worker_shift)
                | self.sequence
            )


_default_generator: SnowflakeGenerator | None = None
_generator_lock = Lock()
_warned_implicit_default_generator = False


def configure_snowflake_generator(
    *,
    datacenter_id: int = 0,
    worker_id: int = 0,
    config: SnowflakeConfig | None = None,
    time_provider: Callable[[], int] | None = None,
) -> SnowflakeGenerator:
    global _default_generator, _warned_implicit_default_generator
    generator = SnowflakeGenerator(
        datacenter_id=datacenter_id,
        worker_id=worker_id,
        config=config,
        time_provider=time_provider,
    )
    with _generator_lock:
        _default_generator = generator
        _warned_implicit_default_generator = False
    return generator


def generate_snowflake_id() -> int:
    global _default_generator, _warned_implicit_default_generator
    with _generator_lock:
        if _default_generator is None:
            if not _warned_implicit_default_generator:
                logger.warning(
                    "Snowflake generator was not configured; "
                    "using default datacenter_id=0 worker_id=0"
                )
                _warned_implicit_default_generator = True
            _default_generator = SnowflakeGenerator(datacenter_id=0, worker_id=0)
        generator = _default_generator
    return generator.generate_id()


def _uuid7(
    *,
    timestamp_ms: int | None = None,
    randbits_fn: Callable[[int], int] = randbits,
) -> UUID:
    """Generate a UUIDv7 using the layout from RFC 4122-bis.

    The timestamp uses Unix milliseconds and is truncated to 60 bits.
    Random bits provide 62 bits of entropy split across the clock sequence and node parts.
    """

    unix_ts_ms = timestamp_ms if timestamp_ms is not None else _current_time_millis()
    unix_ts_ms &= UUID_TIMESTAMP_MASK

    time_low = unix_ts_ms & 0xFFFFFFFF
    time_mid = (unix_ts_ms >> 32) & 0xFFFF
    time_hi_and_version = ((unix_ts_ms >> 48) & 0x0FFF) | UUIDV7_VERSION_BITS

    rand_a = randbits_fn(14)
    clock_seq_hi_and_reserved = UUID_VARIANT_BITS | ((rand_a >> 8) & 0x3F)
    clock_seq_low = rand_a & 0xFF
    node = randbits_fn(48)

    return UUID(
        fields=(
            time_low,
            time_mid,
            time_hi_and_version,
            clock_seq_hi_and_reserved,
            clock_seq_low,
            node,
        )
    )


def generate_uuid7_hex(*, timestamp_ms: int | None = None) -> str:
    """Return a hyphen-less UUIDv7 string (32 hex chars) for storage keys."""

    return _uuid7(timestamp_ms=timestamp_ms).hex
