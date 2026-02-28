"""Deterministic ID helpers for canonical market entities and events."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

import alpha_core.utils.time as time_utils

_JSONType = dict[str, Any] | list[Any] | str | int | float | bool | None


def _to_canonical_json_value(value: Any) -> _JSONType:
    if isinstance(value, datetime):
        return time_utils.ensure_utc(value).isoformat(timespec="microseconds")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, Mapping):
        return {
            str(key): _to_canonical_json_value(inner)
            for key, inner in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_to_canonical_json_value(inner) for inner in value]
    if isinstance(value, set):
        normalized = [_to_canonical_json_value(inner) for inner in value]
        return sorted(
            normalized,
            key=lambda inner: json.dumps(inner, sort_keys=True, separators=(",", ":")),
        )
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def stable_payload_json(payload: Mapping[str, Any], *, exclude_keys: set[str] | None = None) -> str:
    """Serialize a payload into a deterministic JSON representation."""
    excluded = exclude_keys or set()
    filtered = {key: value for key, value in payload.items() if key not in excluded}
    canonical = _to_canonical_json_value(filtered)
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def generate_event_id(payload: Mapping[str, Any], *, exclude_keys: set[str] | None = None) -> str:
    """Generate a deterministic SHA256 event identifier from payload fields."""
    digest_input = stable_payload_json(payload, exclude_keys=exclude_keys)
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
