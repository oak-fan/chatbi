"""Datetime utilities for consistent formatting/parsing."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

APP_TIMEZONE = ZoneInfo("Asia/Shanghai")
_DATETIME_FORMATS = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S")

__all__ = [
    "APP_TIMEZONE",
    "ensure_timezone",
    "now_local",
    "serialize_datetime",
    "parse_datetime",
    "normalize_datetime_str",
]


def now_local() -> datetime:
    """Return current time in UTC+8."""
    return datetime.now(tz=APP_TIMEZONE)


def ensure_timezone(value: datetime) -> datetime:
    """Ensure datetime is timezone-aware and normalized to UTC+8."""
    if value.tzinfo is None:
        return value.replace(tzinfo=APP_TIMEZONE)
    return value.astimezone(APP_TIMEZONE)


def serialize_datetime(value: datetime | None) -> str | None:
    """Format datetime as UTC+8 string (yyyy-MM-dd HH:mm:ss) without timezone suffix."""
    if value is None:
        return None
    target = ensure_timezone(value)
    return target.strftime("%Y-%m-%d %H:%M:%S")


def parse_datetime(value: str | datetime | None) -> datetime | None:
    """Parse string/datetime input into datetime (prefers UTC+8)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_timezone(value)
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
        return ensure_timezone(parsed)
    except ValueError:
        pass

    normalized = normalized.replace("T", " ")
    for fmt in _DATETIME_FORMATS:
        try:
            parsed = datetime.strptime(normalized, fmt)
            return ensure_timezone(parsed)
        except ValueError:
            continue

    return None


def normalize_datetime_str(value: str | datetime) -> str:
    """
    Normalize input into a UTC+8 string (yyyy-MM-dd HH:mm:ss) without timezone suffix.

    - Naive datetimes are treated as UTC+8.
    - Sub-second precision is truncated.
    """

    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError(f"invalid ISO8601 datetime: {value}")
    normalized = serialize_datetime(parsed)
    if normalized is None:
        raise ValueError(f"invalid ISO8601 datetime: {value}")
    return normalized
