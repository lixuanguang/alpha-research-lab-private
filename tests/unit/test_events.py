"""Unit tests for canonical event models and event-level quality checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

import alpha_core.events.models as event_models
import alpha_core.events.quality as event_quality
import alpha_core.events.schema_version as event_schema_version
import alpha_core.utils.ids as ids_utils


def _canonicalize_for_event_id(payload: dict[str, object]) -> dict[str, object]:
    canonical = dict(payload)
    venue_id = canonical.get("venue_id")
    if isinstance(venue_id, str):
        canonical["venue_id"] = venue_id.lower()
    canonical.setdefault("schema_version", event_schema_version.CANONICAL_EVENT_SCHEMA_VERSION)
    # Mirror the model's exclusion set so the hash matches what Pydantic computes.
    for key in event_models._EVENT_ID_EXCLUDE_FIELDS:
        canonical.pop(key, None)
    return canonical


def _with_event_id(payload: dict[str, object]) -> dict[str, object]:
    enriched = dict(payload)
    enriched["event_id"] = ids_utils.generate_event_id(_canonicalize_for_event_id(enriched))
    return enriched


def _refresh_event_id(payload: dict[str, object]) -> dict[str, object]:
    return _with_event_id({key: value for key, value in payload.items() if key != "event_id"})


def _trade_fields() -> dict[str, object]:
    ts_event = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    payload: dict[str, object] = {
        "instrument_id": "polymarket:market-1:yes",
        "venue_id": "POLYMARKET",
        "event_type": event_models.EventType.TRADE,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(seconds=1),
        "price": Decimal("0.61"),
        "size": Decimal("10"),
        "side": event_models.TradeSide.BUY,
        "trade_id": "trade-123",
    }
    return _with_event_id(payload)


def _book_fields() -> dict[str, object]:
    ts_event = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    return _with_event_id(
        {
            "instrument_id": "polymarket:market-1:yes",
            "venue_id": "polymarket",
            "event_type": event_models.EventType.BOOK_SNAPSHOT,
            "ts_event": ts_event,
            "ts_record": ts_event,
            "bids": [{"price": "0.60", "size": "25"}],
            "asks": [{"price": "0.62", "size": "30"}],
        }
    )


def _ohlcv_fields() -> dict[str, object]:
    ts_event = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    return _with_event_id(
        {
            "instrument_id": "polymarket:market-1:yes",
            "venue_id": "polymarket",
            "event_type": event_models.EventType.OHLCV,
            "ts_event": ts_event,
            "ts_record": ts_event,
            "open": "0.50",
            "high": "0.70",
            "low": "0.45",
            "close": "0.65",
            "volume": "120",
            "resolution": "1h",
        }
    )


def _book_delta_fields() -> dict[str, object]:
    ts_event = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    return _with_event_id(
        {
            "instrument_id": "kalshi:market-2:yes",
            "venue_id": "kalshi",
            "event_type": event_models.EventType.BOOK_DELTA,
            "ts_event": ts_event,
            "ts_record": ts_event + timedelta(milliseconds=5),
            "side": "bid",
            "price": Decimal("0.55"),
            "delta_size": Decimal("10"),
            "reason": "add",
        }
    )


def test_construct_trade_event() -> None:
    trade = event_models.CanonicalTrade.model_validate(_trade_fields())

    assert trade.event_type == event_models.EventType.TRADE
    assert trade.price == Decimal("0.61")
    assert trade.venue_id == "polymarket"


def test_construct_book_snapshot_event() -> None:
    book = event_models.CanonicalBookSnapshot.model_validate(_book_fields())

    assert len(book.bids) == 1
    assert book.bids[0].price == Decimal("0.60")


def test_construct_ohlcv_event() -> None:
    ohlcv = event_models.CanonicalOHLCV.model_validate(_ohlcv_fields())

    assert ohlcv.resolution == "1h"
    assert ohlcv.close == Decimal("0.65")


def test_trade_dict_roundtrip_is_lossless_for_decimals() -> None:
    trade = event_models.CanonicalTrade.model_validate(_trade_fields())

    restored = event_models.CanonicalTrade.model_validate(trade.model_dump())

    assert restored == trade
    assert restored.price == Decimal("0.61")


def test_trade_json_roundtrip_is_lossless_for_decimals() -> None:
    trade = event_models.CanonicalTrade.model_validate(_trade_fields())

    restored = event_models.CanonicalTrade.model_validate_json(trade.model_dump_json())

    assert restored == trade


def test_bitemporal_invariant_is_enforced() -> None:
    fields = _trade_fields()
    fields["ts_record"] = datetime(2026, 1, 1, 11, 59, tzinfo=UTC)
    fields = _refresh_event_id(fields)

    with pytest.raises(ValidationError, match="ts_event"):
        event_models.CanonicalTrade.model_validate(fields)


def test_trade_price_must_be_between_zero_and_one() -> None:
    fields = _trade_fields()
    fields["price"] = Decimal("1.01")
    fields = _refresh_event_id(fields)

    with pytest.raises(ValidationError):
        event_models.CanonicalTrade.model_validate(fields)


def test_schema_version_attached_to_all_events() -> None:
    trade = event_models.CanonicalTrade.model_validate(_trade_fields())
    book = event_models.CanonicalBookSnapshot.model_validate(_book_fields())
    ohlcv = event_models.CanonicalOHLCV.model_validate(_ohlcv_fields())

    assert trade.schema_version == event_schema_version.CANONICAL_EVENT_SCHEMA_VERSION
    assert book.schema_version == event_schema_version.CANONICAL_EVENT_SCHEMA_VERSION
    assert ohlcv.schema_version == event_schema_version.CANONICAL_EVENT_SCHEMA_VERSION


def test_event_id_is_deterministic_for_same_payload() -> None:
    fields = _trade_fields()
    canonical_fields = _canonicalize_for_event_id(fields)

    first = ids_utils.generate_event_id(canonical_fields, exclude_keys={"event_id"})
    second = ids_utils.generate_event_id(canonical_fields, exclude_keys={"event_id"})

    assert first == second


def test_event_id_changes_when_payload_changes() -> None:
    fields = _trade_fields()
    before = ids_utils.generate_event_id(
        _canonicalize_for_event_id(fields), exclude_keys={"event_id"}
    )
    fields["trade_id"] = "trade-456"
    after = ids_utils.generate_event_id(
        _canonicalize_for_event_id(fields), exclude_keys={"event_id"}
    )

    assert before != after


def test_event_id_mismatch_is_rejected() -> None:
    fields = _trade_fields()
    fields["event_id"] = "not-a-real-id"

    with pytest.raises(ValidationError, match="event_id"):
        event_models.CanonicalTrade.model_validate(fields)


def test_venue_is_normalized_to_lowercase() -> None:
    trade = event_models.CanonicalTrade.model_validate(_trade_fields())

    assert trade.venue_id == "polymarket"


def test_ohlcv_consistency_constraints_are_enforced() -> None:
    fields = _ohlcv_fields()
    fields["open"] = Decimal("0.9")
    fields["high"] = Decimal("0.8")
    fields = _refresh_event_id(fields)

    with pytest.raises(ValidationError, match="within"):
        event_models.CanonicalOHLCV.model_validate(fields)


def test_quality_checker_passes_valid_trade() -> None:
    checker = event_quality.EventQualityChecker()
    trade = event_models.CanonicalTrade.model_validate(_trade_fields())

    report = checker.check(trade)

    assert report.is_valid is True
    assert report.issues == []


def test_quality_checker_flags_non_monotonic_event_times() -> None:
    checker = event_quality.EventQualityChecker()

    first = event_models.CanonicalTrade.model_validate(_trade_fields())
    second_fields = _trade_fields()
    second_fields["trade_id"] = "trade-124"
    second_fields["ts_event"] = datetime(2026, 1, 1, 11, 59, tzinfo=UTC)
    second_fields["ts_record"] = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    second_fields = _refresh_event_id(second_fields)

    second = event_models.CanonicalTrade.model_validate(second_fields)

    first_report = checker.check(first)
    second_report = checker.check(second)

    assert first_report.is_valid is True
    assert second_report.is_valid is False
    assert any(issue.code == "non_monotonic_event_time" for issue in second_report.issues)


def test_quality_checker_flags_bitemporal_order_violation() -> None:
    checker = event_quality.EventQualityChecker()
    trade = event_models.CanonicalTrade.model_construct(
        event_id="trade-invalid",
        instrument_id="polymarket:market-1:yes",
        venue_id="polymarket",
        event_type=event_models.EventType.TRADE,
        ts_event=datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
        ts_record=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        schema_version=event_schema_version.CANONICAL_EVENT_SCHEMA_VERSION,
        price=Decimal("0.61"),
        size=Decimal("10"),
        side=event_models.TradeSide.BUY,
        trade_id="trade-125",
    )
    report = checker.check(trade)

    assert report.is_valid is False
    assert any(issue.code == "bitemporal_order" for issue in report.issues)


def test_quality_checker_handles_missing_required_fields_without_crashing() -> None:
    checker = event_quality.EventQualityChecker()
    malformed_trade = event_models.CanonicalTrade.model_construct(
        event_id="trade-invalid-missing-size",
        instrument_id="polymarket:market-1:yes",
        venue_id="polymarket",
        event_type=event_models.EventType.TRADE,
        ts_event=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        ts_record=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        schema_version=event_schema_version.CANONICAL_EVENT_SCHEMA_VERSION,
        price=Decimal("0.61"),
        side=event_models.TradeSide.BUY,
        trade_id="trade-126",
    )

    report = checker.check(malformed_trade)

    assert report.is_valid is False
    assert any("`size`" in issue.message for issue in report.issues)


def test_quality_checker_rejects_non_positive_capacity() -> None:
    with pytest.raises(ValueError, match="max_instruments"):
        event_quality.EventQualityChecker(max_instruments=0)


def test_quality_checker_evicts_oldest_instrument_state_when_capacity_exceeded() -> None:
    checker = event_quality.EventQualityChecker(max_instruments=1)

    first = event_models.CanonicalTrade.model_validate(_trade_fields())
    first_report = checker.check(first)

    second_fields = _trade_fields()
    second_fields["instrument_id"] = "polymarket:market-2:yes"
    second_fields["trade_id"] = "trade-200"
    second_fields = _refresh_event_id(second_fields)
    second = event_models.CanonicalTrade.model_validate(second_fields)
    second_report = checker.check(second)

    third_fields = _trade_fields()
    third_fields["trade_id"] = "trade-201"
    third_fields["ts_event"] = datetime(2026, 1, 1, 11, 59, tzinfo=UTC)
    third_fields["ts_record"] = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    third_fields = _refresh_event_id(third_fields)
    third = event_models.CanonicalTrade.model_validate(third_fields)
    third_report = checker.check(third)

    assert first_report.is_valid is True
    assert second_report.is_valid is True
    assert third_report.is_valid is True


# ---------------------------------------------------------------------------
# F3 Extension: CanonicalBookDelta and optional microstructure metadata
# ---------------------------------------------------------------------------


def test_construct_book_delta_event() -> None:
    delta = event_models.CanonicalBookDelta.model_validate(_book_delta_fields())

    assert delta.event_type == event_models.EventType.BOOK_DELTA
    assert delta.side == "bid"
    assert delta.price == Decimal("0.55")
    assert delta.delta_size == Decimal("10")
    assert delta.reason == "add"


def test_book_delta_dict_roundtrip_is_lossless() -> None:
    delta = event_models.CanonicalBookDelta.model_validate(_book_delta_fields())
    restored = event_models.CanonicalBookDelta.model_validate(delta.model_dump())

    assert restored == delta


def test_book_delta_invalid_side_is_rejected() -> None:
    fields = _book_delta_fields()
    fields["side"] = "middle"
    fields = _refresh_event_id(fields)

    with pytest.raises(ValidationError):
        event_models.CanonicalBookDelta.model_validate(fields)


def test_book_delta_invalid_reason_is_rejected() -> None:
    fields = _book_delta_fields()
    fields["reason"] = "unknown"
    fields = _refresh_event_id(fields)

    with pytest.raises(ValidationError):
        event_models.CanonicalBookDelta.model_validate(fields)


def test_book_delta_sequence_id_is_optional() -> None:
    fields = _book_delta_fields()
    fields["sequence_id"] = "seq-00042"
    fields = _refresh_event_id(fields)

    delta = event_models.CanonicalBookDelta.model_validate(fields)

    assert delta.sequence_id == "seq-00042"


def test_optional_microstructure_fields_default_to_none() -> None:
    trade = event_models.CanonicalTrade.model_validate(_trade_fields())

    assert trade.sequence_id is None
    assert trade.ts_exchange is None
    assert trade.ts_receive is None
    assert trade.source_latency_ms is None


def test_optional_microstructure_fields_roundtrip_when_populated() -> None:
    ts_event = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    fields = _with_event_id(
        {
            "instrument_id": "kalshi:market-1:yes",
            "venue_id": "kalshi",
            "event_type": event_models.EventType.TRADE,
            "ts_event": ts_event,
            "ts_record": ts_event + timedelta(milliseconds=10),
            "price": Decimal("0.72"),
            "size": Decimal("5"),
            "side": event_models.TradeSide.SELL,
            "trade_id": "trade-ms-001",
            "sequence_id": "1234567",
            "ts_exchange": ts_event - timedelta(milliseconds=2),
            "ts_receive": ts_event + timedelta(milliseconds=1),
            "source_latency_ms": 3.14,
        }
    )

    trade = event_models.CanonicalTrade.model_validate(fields)
    restored = event_models.CanonicalTrade.model_validate(trade.model_dump())

    assert restored == trade
    assert restored.sequence_id == "1234567"
    assert restored.source_latency_ms == 3.14


def test_optional_ts_fields_are_normalized_to_utc() -> None:
    import zoneinfo

    ts_event = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    eastern = zoneinfo.ZoneInfo("America/New_York")
    ts_exchange_eastern = datetime(2026, 1, 1, 7, 0, tzinfo=eastern)  # same instant as 12:00 UTC
    fields = _with_event_id(
        {
            "instrument_id": "kalshi:market-1:yes",
            "venue_id": "kalshi",
            "event_type": event_models.EventType.TRADE,
            "ts_event": ts_event,
            "ts_record": ts_event + timedelta(milliseconds=5),
            "price": Decimal("0.60"),
            "size": Decimal("1"),
            "side": event_models.TradeSide.BUY,
            "trade_id": "trade-tz-001",
            "ts_exchange": ts_exchange_eastern,
        }
    )

    trade = event_models.CanonicalTrade.model_validate(fields)

    assert trade.ts_exchange is not None
    assert trade.ts_exchange.tzname() == "UTC"


def test_optional_ts_receive_is_normalized_to_utc() -> None:
    import zoneinfo

    ts_event = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    eastern = zoneinfo.ZoneInfo("America/New_York")
    ts_receive_eastern = datetime(2026, 1, 1, 7, 0, 0, 5000, tzinfo=eastern)  # 12:00:00.005 UTC
    fields = _with_event_id(
        {
            "instrument_id": "kalshi:market-1:yes",
            "venue_id": "kalshi",
            "event_type": event_models.EventType.TRADE,
            "ts_event": ts_event,
            "ts_record": ts_event + timedelta(milliseconds=5),
            "price": Decimal("0.60"),
            "size": Decimal("1"),
            "side": event_models.TradeSide.BUY,
            "trade_id": "trade-tz-002",
            "ts_receive": ts_receive_eastern,
        }
    )

    trade = event_models.CanonicalTrade.model_validate(fields)

    assert trade.ts_receive is not None
    assert trade.ts_receive.tzname() == "UTC"


def test_event_id_is_stable_when_optional_metadata_fields_are_added() -> None:
    """Verify that _EVENT_ID_EXCLUDE_FIELDS upholds the core design invariant:
    enriching an event with sequence_id / ts_exchange / ts_receive / source_latency_ms
    must not change its event_id.
    """
    ts_event = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    base_fields: dict[str, object] = {
        "instrument_id": "kalshi:market-1:yes",
        "venue_id": "kalshi",
        "event_type": event_models.EventType.TRADE,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(milliseconds=10),
        "price": Decimal("0.65"),
        "size": Decimal("3"),
        "side": event_models.TradeSide.BUY,
        "trade_id": "trade-stable-001",
    }
    base_trade = event_models.CanonicalTrade.model_validate(_with_event_id(base_fields))

    enriched_fields = dict(base_fields)
    enriched_fields["sequence_id"] = "seq-9999"
    enriched_fields["ts_exchange"] = ts_event - timedelta(milliseconds=3)
    enriched_fields["ts_receive"] = ts_event + timedelta(milliseconds=1)
    enriched_fields["source_latency_ms"] = 4.0
    enriched_fields["event_id"] = base_trade.event_id  # same ID — must remain valid
    enriched_trade = event_models.CanonicalTrade.model_validate(enriched_fields)

    assert enriched_trade.event_id == base_trade.event_id
