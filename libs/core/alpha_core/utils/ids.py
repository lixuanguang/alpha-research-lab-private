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
    normalized_value = value
    if isinstance(normalized_value, datetime):
        normalized_value = time_utils.ensure_utc(normalized_value).isoformat(
            timespec="microseconds"
        )
    elif isinstance(normalized_value, Decimal):
        normalized_value = str(normalized_value)
    elif isinstance(normalized_value, Enum):
        normalized_value = str(normalized_value.value)

    converted: _JSONType
    if isinstance(normalized_value, Mapping):
        converted = {
            str(key): _to_canonical_json_value(inner)
            for key, inner in sorted(normalized_value.items(), key=lambda item: str(item[0]))
        }
    elif isinstance(normalized_value, (list, tuple)):
        converted = [_to_canonical_json_value(inner) for inner in normalized_value]
    elif isinstance(normalized_value, set):
        set_values = [_to_canonical_json_value(inner) for inner in normalized_value]
        converted = sorted(
            set_values,
            key=lambda inner: json.dumps(inner, sort_keys=True, separators=(",", ":")),
        )
    elif isinstance(normalized_value, (str, int, float, bool)) or normalized_value is None:
        converted = normalized_value
    else:
        converted = str(normalized_value)
    return converted


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
