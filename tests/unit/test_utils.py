"""Unit tests for UTC time helpers and deterministic ID generation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import alpha_core.utils.ids as ids_utils
import alpha_core.utils.time as time_utils


def test_ensure_utc_treats_naive_datetime_as_utc() -> None:
    naive = datetime(2026, 2, 1, 9, 30)

    normalized = time_utils.ensure_utc(naive)

    assert normalized.tzinfo == UTC
    assert normalized.hour == 9


def test_ensure_utc_converts_aware_datetime_to_utc() -> None:
    eastern = timezone(timedelta(hours=-5))
    source = datetime(2026, 2, 1, 9, 30, tzinfo=eastern)

    normalized = time_utils.ensure_utc(source)

    assert normalized.tzinfo == UTC
    assert normalized.hour == 14


def test_to_utc_naive_strips_timezone() -> None:
    source = datetime(2026, 2, 1, 9, 30, tzinfo=timezone(timedelta(hours=2)))

    stripped = time_utils.to_utc_naive(source)

    assert stripped.tzinfo is None
    assert stripped.hour == 7


def test_unix_ns_roundtrip_preserves_microseconds() -> None:
    source = datetime(2026, 2, 1, 9, 30, 12, 345678, tzinfo=UTC)

    unix_ns = time_utils.datetime_to_unix_ns(source)
    restored = time_utils.unix_ns_to_datetime(unix_ns)

    assert restored == source


def test_unix_ns_roundtrip_is_stable_for_large_timestamps() -> None:
    source = datetime(2262, 1, 1, 0, 0, 0, 1, tzinfo=UTC)

    unix_ns = time_utils.datetime_to_unix_ns(source)
    restored = time_utils.unix_ns_to_datetime(unix_ns)

    assert restored == source


def test_generate_event_id_is_deterministic() -> None:
    payload = {
        "instrument_id": "polymarket:market-1:yes",
        "price": Decimal("0.55"),
        "ts_event": datetime(2026, 2, 1, 9, 30, tzinfo=UTC),
        "side": "buy",
    }

    first = ids_utils.generate_event_id(payload)
    second = ids_utils.generate_event_id(payload)

    assert first == second


def test_generate_event_id_is_key_order_independent() -> None:
    left = {
        "a": 1,
        "b": Decimal("0.1"),
        "c": datetime(2026, 2, 1, 9, 30, tzinfo=UTC),
    }
    right = {
        "c": datetime(2026, 2, 1, 9, 30, tzinfo=UTC),
        "a": 1,
        "b": Decimal("0.1"),
    }

    assert ids_utils.generate_event_id(left) == ids_utils.generate_event_id(right)


def test_generate_event_id_changes_for_different_payload() -> None:
    base = {
        "instrument_id": "polymarket:market-1:yes",
        "price": Decimal("0.55"),
        "ts_event": datetime(2026, 2, 1, 9, 30, tzinfo=UTC),
    }
    changed = {
        "instrument_id": "polymarket:market-1:yes",
        "price": Decimal("0.56"),
        "ts_event": datetime(2026, 2, 1, 9, 30, tzinfo=UTC),
    }

    assert ids_utils.generate_event_id(base) != ids_utils.generate_event_id(changed)
