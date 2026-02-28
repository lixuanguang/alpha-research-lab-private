"""Time utility helpers for canonical UTC event handling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_UNIX_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Return a timezone-aware UTC datetime.

    Naive datetimes are interpreted as UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_utc_naive(dt: datetime) -> datetime:
    """Normalize to UTC, then strip timezone info."""
    return ensure_utc(dt).replace(tzinfo=None)


def datetime_to_unix_ns(dt: datetime) -> int:
    """Convert a datetime to Unix epoch nanoseconds."""
    dt_utc = ensure_utc(dt)
    delta = dt_utc - _UNIX_EPOCH_UTC
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def unix_ns_to_datetime(unix_ns: int) -> datetime:
    """Convert Unix epoch nanoseconds to a UTC datetime.

    Python's datetime is microsecond precision; nanoseconds are truncated.
    """
    return _UNIX_EPOCH_UTC + timedelta(microseconds=unix_ns // 1_000)
