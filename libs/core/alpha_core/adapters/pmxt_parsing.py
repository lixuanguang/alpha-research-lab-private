"""Low-level parsing and coercion helpers for pmxt payload normalization."""

from __future__ import annotations

import inspect
import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import alpha_core.utils.time as time_utils


def pick(raw: object, *keys: str, default: object = None) -> object:
    """Return the first matching key/attribute from a vendor payload object."""
    if isinstance(raw, dict):
        for key in keys:
            if key in raw:
                return raw[key]

    for key in keys:
        if hasattr(raw, key):
            return getattr(raw, key)

    return default


def coerce_optional_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def coerce_required_text(value: object) -> str:
    text = coerce_optional_text(value)
    if text is None:
        raise ValueError("required text field is missing")
    return text


def coerce_tags(value: object) -> list[str]:
    if isinstance(value, list):
        tags = [str(tag).strip() for tag in value]
        return [tag for tag in tags if tag]
    if value is None:
        return []
    single = str(value).strip()
    return [single] if single else []


def coerce_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None


def coerce_event_time(value: object, fallback: datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return time_utils.ensure_utc(value)

    if isinstance(value, (int, float)):
        timestamp = float(value)
        if not math.isfinite(timestamp):
            return fallback
        if abs(timestamp) > 1_000_000_000_000:
            timestamp = timestamp / 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return fallback

    if isinstance(value, str):
        parsed = _parse_datetime_text(value)
        if parsed is not None:
            return parsed

    return fallback


def supported_kwargs(method: Any, kwargs: dict[str, object]) -> dict[str, object]:
    """Filter keyword arguments to those accepted by the target method signature."""
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return kwargs

    parameters = signature.parameters.values()
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return kwargs

    accepted_names = {
        name
        for name, parameter in signature.parameters.items()
        if parameter.kind
        in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }
    return {name: value for name, value in kwargs.items() if name in accepted_names}


def normalize_resolution(resolution: str) -> str:
    return resolution if resolution in {"1m", "5m", "1h", "1d"} else "1h"


def bound_event_time(ts_event: datetime, ts_record: datetime) -> datetime:
    if ts_event > ts_record:
        return ts_record
    return ts_event


def _parse_datetime_text(value: str) -> datetime | None:
    stripped = value.strip()
    if not stripped:
        return None

    normalized = stripped.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    return time_utils.ensure_utc(parsed)
