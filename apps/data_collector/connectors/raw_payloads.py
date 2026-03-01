"""Helpers for normalizing raw venue payloads for bronze storage."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal


def normalize_raw_payloads(
    raw_payloads: list[object],
    *,
    outcome_id: str,
) -> list[dict[str, object]]:
    """Return raw payloads normalized into JSON-serializable dictionaries."""
    normalized_payloads: list[dict[str, object]] = []
    for payload in raw_payloads:
        normalized = _to_json_compatible(payload)
        if isinstance(normalized, dict):
            materialized = dict(normalized)
            materialized.setdefault("outcome_id", outcome_id)
            normalized_payloads.append(materialized)
            continue
        normalized_payloads.append({"outcome_id": outcome_id, "payload": normalized})
    return normalized_payloads


def _to_json_compatible(value: object) -> object:
    if hasattr(value, "model_dump"):
        model_dump = getattr(value, "model_dump")
        if callable(model_dump):
            dumped = model_dump(mode="json")
            return _to_json_compatible(dumped)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_to_json_compatible(item) for item in value]
    if isinstance(value, tuple):
        return [_to_json_compatible(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_json_compatible(item) for key, item in value.items()}
    serialized = json.dumps(value, default=str, separators=(",", ":"))
    return json.loads(serialized)


__all__ = ["normalize_raw_payloads"]
