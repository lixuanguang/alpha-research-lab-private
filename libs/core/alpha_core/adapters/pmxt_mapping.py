"""Vendor payload mapping helpers for pmxt-backed adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import alpha_core.adapters.pmxt_parsing as pmxt_parsing
import alpha_core.adapters.venue_configs as venue_configs
import alpha_core.events.models as event_models
import alpha_core.events.schema_version as event_schema_version
import alpha_core.instruments.models as instrument_models
import alpha_core.instruments.symbology as instrument_symbology
import alpha_core.utils.ids as id_utils


def map_market(raw: object, *, venue: str) -> instrument_models.MarketSpec:
    """Map one raw market payload into a canonical market spec."""
    market_id = pmxt_parsing.coerce_required_text(
        pmxt_parsing.pick(raw, "id", "market_id", "symbol")
    )
    title = pmxt_parsing.coerce_optional_text(pmxt_parsing.pick(raw, "title", "question", "name"))
    outcomes = map_outcomes(
        market_id=market_id,
        raw_outcomes=cast(list[object], pmxt_parsing.pick(raw, "outcomes", default=[])),
        venue=venue,
    )

    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "market_id": market_id,
        "venue": venue,
        "title": title or market_id,
        "description": pmxt_parsing.coerce_optional_text(
            pmxt_parsing.pick(raw, "description", "details")
        ),
        "category": pmxt_parsing.coerce_optional_text(pmxt_parsing.pick(raw, "category", "group")),
        "tags": pmxt_parsing.coerce_tags(pmxt_parsing.pick(raw, "tags", default=[])),
        "outcomes": outcomes,
        "resolution_date": pmxt_parsing.coerce_event_time(
            pmxt_parsing.pick(raw, "resolution_date", "close_time", "expiry", default=None),
            fallback=None,
        ),
        "lifecycle": map_lifecycle(raw),
        "volume": pmxt_parsing.coerce_decimal(pmxt_parsing.pick(raw, "volume", default=None)),
        "liquidity": pmxt_parsing.coerce_decimal(pmxt_parsing.pick(raw, "liquidity", default=None)),
        "url": pmxt_parsing.coerce_optional_text(
            pmxt_parsing.pick(raw, "url", "market_url", default=None)
        ),
        "first_seen": now,
        "last_updated": now,
    }
    return instrument_models.MarketSpec.model_validate(payload)


def map_trade(
    raw: object,
    *,
    venue: str,
    instrument_id: str,
    quirks: venue_configs.VenueQuirks,
) -> event_models.CanonicalTrade:
    """Map one raw trade payload into a canonical trade event."""
    ts_record = datetime.now(tz=UTC)
    ts_event = pmxt_parsing.coerce_event_time(
        pmxt_parsing.pick(raw, "timestamp", "ts", "time", "datetime", default=ts_record),
        fallback=ts_record,
    )
    if ts_event is None:
        ts_event = ts_record
    ts_event = pmxt_parsing.bound_event_time(ts_event=ts_event, ts_record=ts_record)

    price = pmxt_parsing.coerce_decimal(pmxt_parsing.pick(raw, "price", default=None))
    if price is None:
        raise ValueError("trade price is required")

    size = pmxt_parsing.coerce_decimal(
        pmxt_parsing.pick(raw, "size", "amount", "quantity", default=None)
    )
    if size is None or size <= 0:
        raise ValueError("trade size must be positive")

    side = map_side(
        pmxt_parsing.pick(raw, "side", "taker_side", default="buy"),
        quirks=quirks,
    )
    trade_id = pmxt_parsing.coerce_optional_text(
        pmxt_parsing.pick(raw, "id", "trade_id", default=None)
    )
    if trade_id is None:
        trade_id = id_utils.generate_event_id(
            {
                "venue": venue,
                "instrument_id": instrument_id,
                "ts_event": ts_event,
                "price": price,
                "size": size,
                "side": side,
            }
        )

    payload: dict[str, Any] = {
        "instrument_id": instrument_id,
        "venue_id": venue,
        "event_type": event_models.EventType.TRADE,
        "ts_event": ts_event,
        "ts_record": ts_record,
        "schema_version": event_schema_version.CANONICAL_EVENT_SCHEMA_VERSION,
        "price": normalize_price(price, quirks=quirks),
        "size": size,
        "side": side,
        "trade_id": trade_id,
    }
    payload["event_id"] = id_utils.generate_event_id(payload)
    return event_models.CanonicalTrade.model_validate(
        payload, context={"skip_event_id_validation": True}
    )


def map_outcomes(market_id: str, raw_outcomes: list[object], *, venue: str) -> list[dict[str, str]]:
    outcomes: list[dict[str, str]] = []
    for index, raw_outcome in enumerate(raw_outcomes):
        default_outcome_id = f"outcome-{index}"
        outcome_id = (
            pmxt_parsing.coerce_optional_text(
                pmxt_parsing.pick(raw_outcome, "id", "outcome_id", "value", "slug", default=None)
            )
            or default_outcome_id
        )
        label = (
            pmxt_parsing.coerce_optional_text(
                pmxt_parsing.pick(raw_outcome, "label", "name", "title", default=None)
            )
            or outcome_id
        )
        outcomes.append(
            {
                "outcome_id": outcome_id,
                "label": label,
                "canonical_id": instrument_symbology.make_canonical_outcome_id(
                    venue,
                    market_id,
                    outcome_id,
                ),
            }
        )

    if outcomes:
        return outcomes

    fallback_outcome_id = "outcome-0"
    return [
        {
            "outcome_id": fallback_outcome_id,
            "label": "Outcome 0",
            "canonical_id": instrument_symbology.make_canonical_outcome_id(
                venue,
                market_id,
                fallback_outcome_id,
            ),
        }
    ]


def parse_book_level(
    raw_level: object,
    *,
    quirks: venue_configs.VenueQuirks,
) -> dict[str, Decimal] | None:
    price_value: object
    size_value: object

    if isinstance(raw_level, (list, tuple)) and len(raw_level) >= 2:
        price_value, size_value = raw_level[0], raw_level[1]
    else:
        price_value = pmxt_parsing.pick(raw_level, "price", default=None)
        size_value = pmxt_parsing.pick(raw_level, "size", "amount", "quantity", default=None)

    price = pmxt_parsing.coerce_decimal(price_value)
    size = pmxt_parsing.coerce_decimal(size_value)
    if price is None or size is None or size < 0:
        return None
    return {"price": normalize_price(price, quirks=quirks), "size": size}


def parse_ohlcv(
    raw: object,
    *,
    quirks: venue_configs.VenueQuirks,
) -> tuple[datetime, Decimal, Decimal, Decimal, Decimal, Decimal] | None:
    ts_record = datetime.now(tz=UTC)
    if isinstance(raw, (list, tuple)) and len(raw) >= 6:
        timestamp_value = raw[0]
        open_value = raw[1]
        high_value = raw[2]
        low_value = raw[3]
        close_value = raw[4]
        volume_value = raw[5]
    else:
        timestamp_value = pmxt_parsing.pick(raw, "timestamp", "ts", "time", default=ts_record)
        open_value = pmxt_parsing.pick(raw, "open", default=None)
        high_value = pmxt_parsing.pick(raw, "high", default=None)
        low_value = pmxt_parsing.pick(raw, "low", default=None)
        close_value = pmxt_parsing.pick(raw, "close", default=None)
        volume_value = pmxt_parsing.pick(raw, "volume", default=Decimal("0"))

    open_price = pmxt_parsing.coerce_decimal(open_value)
    high_price = pmxt_parsing.coerce_decimal(high_value)
    low_price = pmxt_parsing.coerce_decimal(low_value)
    close_price = pmxt_parsing.coerce_decimal(close_value)
    volume = pmxt_parsing.coerce_decimal(volume_value)
    if None in {open_price, high_price, low_price, close_price, volume}:
        return None

    ts_event = pmxt_parsing.coerce_event_time(timestamp_value, fallback=ts_record)
    if ts_event is None:
        return None
    return (
        ts_event,
        normalize_price(cast(Decimal, open_price), quirks=quirks),
        normalize_price(cast(Decimal, high_price), quirks=quirks),
        normalize_price(cast(Decimal, low_price), quirks=quirks),
        normalize_price(cast(Decimal, close_price), quirks=quirks),
        cast(Decimal, volume),
    )


def normalize_price(price: Decimal, *, quirks: venue_configs.VenueQuirks) -> Decimal:
    scale = quirks.price_scale
    if scale == 0:
        return price
    if price <= Decimal("1"):
        return price
    return price / scale


def map_side(raw_side: object, *, quirks: venue_configs.VenueQuirks) -> event_models.TradeSide:
    side_key = str(raw_side).strip().lower()
    canonical = quirks.side_aliases.get(side_key, side_key)
    if canonical == event_models.TradeSide.BUY.value:
        return event_models.TradeSide.BUY
    if canonical == event_models.TradeSide.SELL.value:
        return event_models.TradeSide.SELL
    raise ValueError(f"Unsupported trade side value: {raw_side}")


def map_lifecycle(raw_market: object) -> instrument_models.MarketLifecycle:
    status = pmxt_parsing.coerce_optional_text(
        pmxt_parsing.pick(raw_market, "status", "state", "lifecycle", default=None)
    )
    if status is None:
        is_active = pmxt_parsing.pick(raw_market, "active", default=True)
        return (
            instrument_models.MarketLifecycle.ACTIVE
            if bool(is_active)
            else instrument_models.MarketLifecycle.HALTED
        )

    normalized = status.lower()
    if normalized in {"active", "open", "trading"}:
        return instrument_models.MarketLifecycle.ACTIVE
    if normalized in {"halted", "paused", "suspended"}:
        return instrument_models.MarketLifecycle.HALTED
    if normalized in {"resolved", "closed", "settled"}:
        return instrument_models.MarketLifecycle.RESOLVED
    if normalized in {"delisted", "cancelled", "canceled"}:
        return instrument_models.MarketLifecycle.DELISTED
    return instrument_models.MarketLifecycle.ACTIVE


def resolve_instrument_id(
    outcome_id: str,
    *,
    venue: str,
    outcome_market_index: dict[str, set[str]],
) -> str:
    candidate = outcome_id.strip()
    if not candidate:
        raise ValueError("`outcome_id` must be non-empty")

    parts = candidate.split(":")
    if len(parts) == 3:
        parsed_venue, market_id, raw_outcome_id = instrument_symbology.parse_canonical_outcome_id(
            candidate
        )
        if parsed_venue != venue:
            raise ValueError(
                f"Canonical `outcome_id` venue mismatch: expected `{venue}`, got `{parsed_venue}`"
            )
        return instrument_symbology.make_canonical_outcome_id(venue, market_id, raw_outcome_id)

    if len(parts) > 1:
        raise ValueError(
            "Invalid `outcome_id` format; expected `{venue}:{market_id}:{outcome_id}` "
            "or a raw non-canonical id without separators"
        )

    market_ids = outcome_market_index.get(candidate)
    if not market_ids:
        raise ValueError(
            f"Unknown non-canonical `outcome_id` `{candidate}`. "
            "Pass canonical ids or call `fetch_markets()` first."
        )
    if len(market_ids) > 1:
        raise ValueError(
            f"Ambiguous non-canonical `outcome_id` `{candidate}` across markets: "
            f"{sorted(market_ids)}. Pass canonical ids."
        )

    market_id = next(iter(market_ids))
    return instrument_symbology.make_canonical_outcome_id(venue, market_id, candidate)
