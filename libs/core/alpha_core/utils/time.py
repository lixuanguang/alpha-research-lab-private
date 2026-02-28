"""Time utility helpers for canonical UTC event handling."""

from __future__ import annotations

from datetime import UTC, datetime


def ensure_utc(dt: datetime) -> datetime:
    """Return a timezone-aware UTC datetime.

    Naive datetimes are interpreted as UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
