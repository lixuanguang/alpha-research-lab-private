"""Provide shared strict wire-record and UTC validation behavior."""

from __future__ import annotations

# standard library imports
from datetime import datetime, timedelta

# third party library imports
import msgspec

# project library imports


class WireRecord(msgspec.Struct, frozen=True, kw_only=True, forbid_unknown_fields=True):
    """Keep authored reference timestamps strictly UTC without normalization."""

    @staticmethod
    def _require_utc(value: object, *, field_name: str) -> datetime:
        """Require an aware datetime whose offset is exactly UTC."""
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TypeError(f"{field_name} must be a timezone-aware datetime")
        if value.utcoffset() != timedelta(0):
            raise ValueError(f"{field_name} must use UTC")
        return value
