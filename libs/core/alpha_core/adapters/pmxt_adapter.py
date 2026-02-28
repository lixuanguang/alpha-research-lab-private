"""pmxt-backed venue adapter implementation."""

from __future__ import annotations

import inspect
import logging
import math
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from pydantic import ValidationError

import alpha_core.adapters.base as adapters_base
import alpha_core.adapters.venue_configs as venue_configs
import alpha_core.config.models as config_models
import alpha_core.config.secrets as secrets
import alpha_core.events.models as event_models
import alpha_core.events.schema_version as event_schema_version
import alpha_core.instruments.models as instrument_models
import alpha_core.instruments.symbology as instrument_symbology
import alpha_core.utils.ids as id_utils
import alpha_core.utils.time as time_utils

try:
    import pmxt as pmxt_module  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    pmxt_module = None


class PmxtAdapter(adapters_base.VenueAdapter):
    """Maps pmxt exchange responses into canonical alpha-core models."""

    def __init__(self, exchange_name: str, config: config_models.VenueConfig) -> None:
        if pmxt_module is None:
            raise ImportError("pmxt is required for PmxtAdapter")

        self._venue = venue_configs.normalize_venue_name(exchange_name)
        self._quirks = venue_configs.get_venue_quirks(self._venue)
        self._capabilities = venue_configs.get_venue_capabilities(self._venue)
        expected_exchange_class = venue_configs.get_exchange_class_name(self._venue)
        if config.exchange_class != expected_exchange_class:
            raise ValueError(
                "Config exchange class mismatch for venue "
                f"`{self._venue}`: expected `{expected_exchange_class}`, "
                f"got `{config.exchange_class}`"
            )

        exchange_cls = getattr(pmxt_module, expected_exchange_class, None)
        if exchange_cls is None:
            raise AttributeError(f"pmxt is missing exchange class `{expected_exchange_class}`")
        self._exchange = exchange_cls(
            api_key=secrets.resolve_secret(config.api_key_env),
            private_key=secrets.resolve_secret(config.private_key_env),
        )

        self._logger = logging.getLogger(__name__)
        self._outcome_market_index: dict[str, set[str]] = {}
        self._rejection_counts: Counter[str] = Counter()

    def venue_name(self) -> str:
        return self._venue

    def rejection_counters(self) -> dict[str, int]:
        """Return cumulative dropped-row counters grouped by scope and reason."""
        return dict(sorted(self._rejection_counts.items()))

    def reset_rejection_counters(self) -> None:
        """Reset cumulative dropped-row counters."""
        self._rejection_counts.clear()

    async def fetch_markets(self) -> list[instrument_models.MarketSpec]:
        self._require_capability("fetch_markets")
        raw_markets = cast(list[object], self._invoke_exchange("fetch_markets"))
        self._outcome_market_index.clear()

        dropped: Counter[str] = Counter()
        mapped_markets: list[instrument_models.MarketSpec] = []
        for raw_market in raw_markets:
            try:
                market = self._map_market(raw_market)
            except (TypeError, ValueError, ValidationError):
                self._record_rejection("markets", "invalid_payload", dropped)
                continue

            for outcome in market.outcomes:
                market_ids = self._outcome_market_index.setdefault(outcome.outcome_id, set())
                market_ids.add(market.market_id)
            mapped_markets.append(market)

        self._log_rejection_summary("markets", dropped)
        return mapped_markets

    async def fetch_trades(
        self,
        outcome_id: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[event_models.CanonicalTrade]:
        self._require_capability("fetch_trades")
        instrument_id = self._instrument_id(outcome_id)
        raw_trades = cast(
            list[object],
            self._invoke_exchange(
                "fetch_trades",
                outcome_id,
                since=since,
                limit=limit,
            ),
        )

        dropped: Counter[str] = Counter()
        mapped: list[event_models.CanonicalTrade] = []
        for raw_trade in raw_trades:
            try:
                mapped.append(self._map_trade(raw_trade, instrument_id))
            except (TypeError, ValueError, ValidationError):
                self._record_rejection("trades", "invalid_payload", dropped)
                continue
        self._log_rejection_summary("trades", dropped)
        return mapped

    async def fetch_order_book(self, outcome_id: str) -> event_models.CanonicalBookSnapshot:
        self._require_capability("fetch_order_book")
        raw_book = self._invoke_exchange("fetch_order_book", outcome_id)

        ts_record = datetime.now(tz=UTC)
        ts_event = self._coerce_event_time(
            self._pick(raw_book, "timestamp", "ts", "time", default=ts_record),
            fallback=ts_record,
        )
        if ts_event is None:
            ts_event = ts_record
        ts_event = self._bound_event_time(ts_event=ts_event, ts_record=ts_record)
        instrument_id = self._instrument_id(outcome_id)
        dropped: Counter[str] = Counter()

        payload: dict[str, Any] = {
            "instrument_id": instrument_id,
            "venue_id": self._venue,
            "event_type": event_models.EventType.BOOK_SNAPSHOT,
            "ts_event": ts_event,
            "ts_record": ts_record,
            "schema_version": event_schema_version.CANONICAL_EVENT_SCHEMA_VERSION,
            "bids": self._map_book_levels(
                self._pick(raw_book, "bids", default=[]),
                side="bids",
                dropped=dropped,
            ),
            "asks": self._map_book_levels(
                self._pick(raw_book, "asks", default=[]),
                side="asks",
                dropped=dropped,
            ),
        }
        payload["event_id"] = id_utils.generate_event_id(payload)
        book = event_models.CanonicalBookSnapshot.model_validate(payload)
        self._log_rejection_summary("book", dropped)
        return book

    async def fetch_ohlcv(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> list[event_models.CanonicalOHLCV]:
        self._require_capability("fetch_ohlcv")
        raw_ohlcv = cast(
            list[object],
            self._invoke_exchange(
                "fetch_ohlcv",
                outcome_id,
                resolution=resolution,
                limit=limit,
            ),
        )

        instrument_id = self._instrument_id(outcome_id)
        dropped: Counter[str] = Counter()
        mapped: list[event_models.CanonicalOHLCV] = []

        for candle in raw_ohlcv:
            ts_record = datetime.now(tz=UTC)
            parsed = self._parse_ohlcv(candle)
            if parsed is None:
                self._record_rejection("ohlcv", "invalid_payload", dropped)
                continue

            ts_event, open_price, high_price, low_price, close_price, volume = parsed
            bounded_ts_event = self._bound_event_time(ts_event=ts_event, ts_record=ts_record)
            payload: dict[str, Any] = {
                "instrument_id": instrument_id,
                "venue_id": self._venue,
                "event_type": event_models.EventType.OHLCV,
                "ts_event": bounded_ts_event,
                "ts_record": ts_record,
                "schema_version": event_schema_version.CANONICAL_EVENT_SCHEMA_VERSION,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
                "resolution": self._normalize_resolution(resolution),
            }
            payload["event_id"] = id_utils.generate_event_id(payload)
            try:
                mapped.append(event_models.CanonicalOHLCV.model_validate(payload))
            except ValidationError:
                self._record_rejection("ohlcv", "invalid_event", dropped)
                continue

        self._log_rejection_summary("ohlcv", dropped)
        return mapped

    def _map_market(self, raw: object) -> instrument_models.MarketSpec:
        market_id = self._coerce_required_text(self._pick(raw, "id", "market_id", "symbol"))
        title = (
            self._coerce_optional_text(self._pick(raw, "title", "question", "name")) or market_id
        )

        outcomes = self._map_outcomes(
            market_id=market_id,
            raw_outcomes=cast(list[object], self._pick(raw, "outcomes", default=[])),
        )

        now = datetime.now(tz=UTC)
        resolution_date = self._coerce_event_time(
            self._pick(raw, "resolution_date", "close_time", "expiry", default=None),
            fallback=None,
        )

        payload: dict[str, Any] = {
            "market_id": market_id,
            "venue": self._venue,
            "title": title,
            "description": self._coerce_optional_text(self._pick(raw, "description", "details")),
            "category": self._coerce_optional_text(self._pick(raw, "category", "group")),
            "tags": self._coerce_tags(self._pick(raw, "tags", default=[])),
            "outcomes": outcomes,
            "resolution_date": resolution_date,
            "lifecycle": self._map_lifecycle(raw),
            "volume": self._coerce_decimal(self._pick(raw, "volume", default=None)),
            "liquidity": self._coerce_decimal(self._pick(raw, "liquidity", default=None)),
            "url": self._coerce_optional_text(
                self._pick(raw, "url", "market_url", default=None)
            ),
            "first_seen": now,
            "last_updated": now,
        }
        return instrument_models.MarketSpec.model_validate(payload)

    def _map_trade(self, raw: object, instrument_id: str) -> event_models.CanonicalTrade:
        ts_record = datetime.now(tz=UTC)
        ts_event = self._coerce_event_time(
            self._pick(raw, "timestamp", "ts", "time", "datetime", default=ts_record),
            fallback=ts_record,
        )
        if ts_event is None:
            ts_event = ts_record
        ts_event = self._bound_event_time(ts_event=ts_event, ts_record=ts_record)

        price = self._coerce_decimal(self._pick(raw, "price", default=None))
        if price is None:
            raise ValueError("trade price is required")

        size = self._coerce_decimal(self._pick(raw, "size", "amount", "quantity", default=None))
        if size is None or size <= 0:
            raise ValueError("trade size must be positive")

        side = self._map_side(self._pick(raw, "side", "taker_side", default="buy"))
        trade_id = self._coerce_optional_text(self._pick(raw, "id", "trade_id", default=None))
        if trade_id is None:
            trade_id = id_utils.generate_event_id(
                {
                    "venue": self._venue,
                    "instrument_id": instrument_id,
                    "ts_event": ts_event,
                    "price": price,
                    "size": size,
                    "side": side,
                }
            )

        payload: dict[str, Any] = {
            "instrument_id": instrument_id,
            "venue_id": self._venue,
            "event_type": event_models.EventType.TRADE,
            "ts_event": ts_event,
            "ts_record": ts_record,
            "schema_version": event_schema_version.CANONICAL_EVENT_SCHEMA_VERSION,
            "price": self._normalize_price(price),
            "size": size,
            "side": side,
            "trade_id": trade_id,
        }
        payload["event_id"] = id_utils.generate_event_id(payload)
        return event_models.CanonicalTrade.model_validate(payload)

    def _map_outcomes(self, market_id: str, raw_outcomes: list[object]) -> list[dict[str, str]]:
        outcomes: list[dict[str, str]] = []
        for index, raw_outcome in enumerate(raw_outcomes):
            default_outcome_id = f"outcome-{index}"
            outcome_id = (
                self._coerce_optional_text(
                    self._pick(raw_outcome, "id", "outcome_id", "value", "slug", default=None)
                )
                or default_outcome_id
            )
            label = (
                self._coerce_optional_text(
                    self._pick(raw_outcome, "label", "name", "title", default=None)
                )
                or outcome_id
            )
            outcomes.append(
                {
                    "outcome_id": outcome_id,
                    "label": label,
                    "canonical_id": instrument_symbology.make_canonical_outcome_id(
                        self._venue,
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
                    self._venue,
                    market_id,
                    fallback_outcome_id,
                ),
            }
        ]

    def _map_book_levels(
        self,
        raw_levels: object,
        *,
        side: str,
        dropped: Counter[str],
    ) -> list[dict[str, Decimal]]:
        if not isinstance(raw_levels, list):
            self._record_rejection("book", f"{side}_not_list", dropped)
            return []

        levels: list[dict[str, Decimal]] = []
        for raw_level in raw_levels:
            mapped = self._parse_book_level(raw_level)
            if mapped is None:
                self._record_rejection("book", f"{side}_invalid_level", dropped)
                continue
            levels.append(mapped)
        return levels

    def _parse_book_level(self, raw_level: object) -> dict[str, Decimal] | None:
        price_value: object
        size_value: object

        if isinstance(raw_level, (list, tuple)) and len(raw_level) >= 2:
            price_value, size_value = raw_level[0], raw_level[1]
        else:
            price_value = self._pick(raw_level, "price", default=None)
            size_value = self._pick(raw_level, "size", "amount", "quantity", default=None)

        price = self._coerce_decimal(price_value)
        size = self._coerce_decimal(size_value)
        if price is None or size is None or size < 0:
            return None
        return {"price": self._normalize_price(price), "size": size}

    def _parse_ohlcv(
        self,
        raw: object,
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
            timestamp_value = self._pick(raw, "timestamp", "ts", "time", default=ts_record)
            open_value = self._pick(raw, "open", default=None)
            high_value = self._pick(raw, "high", default=None)
            low_value = self._pick(raw, "low", default=None)
            close_value = self._pick(raw, "close", default=None)
            volume_value = self._pick(raw, "volume", default=Decimal("0"))

        open_price = self._coerce_decimal(open_value)
        high_price = self._coerce_decimal(high_value)
        low_price = self._coerce_decimal(low_value)
        close_price = self._coerce_decimal(close_value)
        volume = self._coerce_decimal(volume_value)
        if None in {open_price, high_price, low_price, close_price, volume}:
            return None

        ts_event = self._coerce_event_time(timestamp_value, fallback=ts_record)
        if ts_event is None:
            return None
        return (
            ts_event,
            self._normalize_price(cast(Decimal, open_price)),
            self._normalize_price(cast(Decimal, high_price)),
            self._normalize_price(cast(Decimal, low_price)),
            self._normalize_price(cast(Decimal, close_price)),
            cast(Decimal, volume),
        )

    def _normalize_price(self, price: Decimal) -> Decimal:
        scale = self._quirks.price_scale
        if scale == 0:
            return price
        scaled = price / scale
        if scaled > Decimal("1") and price <= Decimal("1"):
            return price
        return scaled

    def _map_side(self, raw_side: object) -> event_models.TradeSide:
        side_key = str(raw_side).strip().lower()
        canonical = self._quirks.side_aliases.get(side_key, side_key)
        if canonical == event_models.TradeSide.BUY.value:
            return event_models.TradeSide.BUY
        if canonical == event_models.TradeSide.SELL.value:
            return event_models.TradeSide.SELL
        raise ValueError(f"Unsupported trade side value: {raw_side}")

    def _map_lifecycle(self, raw_market: object) -> instrument_models.MarketLifecycle:
        status = self._coerce_optional_text(
            self._pick(raw_market, "status", "state", "lifecycle", default=None)
        )
        if status is None:
            is_active = self._pick(raw_market, "active", default=True)
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

    def _instrument_id(self, outcome_id: str) -> str:
        candidate = outcome_id.strip()
        if not candidate:
            raise ValueError("`outcome_id` must be non-empty")

        parts = candidate.split(":")
        if len(parts) == 3:
            venue, market_id, raw_outcome_id = instrument_symbology.parse_canonical_outcome_id(
                candidate
            )
            if venue != self._venue:
                raise ValueError(
                    "Canonical `outcome_id` venue mismatch: "
                    f"expected `{self._venue}`, got `{venue}`"
                )
            return instrument_symbology.make_canonical_outcome_id(
                self._venue,
                market_id,
                raw_outcome_id,
            )

        if len(parts) > 1:
            raise ValueError(
                "Invalid `outcome_id` format; expected `{venue}:{market_id}:{outcome_id}` "
                "or a raw non-canonical id without separators"
            )

        market_ids = self._outcome_market_index.get(candidate)
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
        return instrument_symbology.make_canonical_outcome_id(self._venue, market_id, candidate)

    @staticmethod
    def _pick(raw: object, *keys: str, default: object = None) -> object:
        if isinstance(raw, dict):
            for key in keys:
                if key in raw:
                    return raw[key]

        for key in keys:
            if hasattr(raw, key):
                return getattr(raw, key)

        return default

    @staticmethod
    def _coerce_required_text(value: object) -> str:
        text = PmxtAdapter._coerce_optional_text(value)
        if text is None:
            raise ValueError("required text field is missing")
        return text

    @staticmethod
    def _coerce_optional_text(value: object) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @staticmethod
    def _coerce_tags(value: object) -> list[str]:
        if isinstance(value, list):
            tags = [str(tag).strip() for tag in value]
            return [tag for tag in tags if tag]
        if value is None:
            return []
        single = str(value).strip()
        return [single] if single else []

    @staticmethod
    def _coerce_decimal(value: object) -> Decimal | None:
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

    @staticmethod
    def _coerce_event_time(value: object, fallback: datetime | None) -> datetime | None:
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

    def _invoke_exchange(self, method_name: str, *args: object, **kwargs: object) -> object:
        method = getattr(self._exchange, method_name)
        if not kwargs:
            return method(*args)

        supported_kwargs = self._supported_kwargs(method, kwargs)
        return method(*args, **supported_kwargs)

    @staticmethod
    def _supported_kwargs(method: Any, kwargs: dict[str, object]) -> dict[str, object]:
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
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        }
        return {name: value for name, value in kwargs.items() if name in accepted_names}

    def _require_capability(self, capability_name: str) -> None:
        if not getattr(self._capabilities, capability_name):
            raise NotImplementedError(
                f"Venue `{self._venue}` does not support `{capability_name}`"
            )

    def _record_rejection(self, scope: str, reason: str, dropped: Counter[str]) -> None:
        key = f"{scope}.{reason}"
        self._rejection_counts[key] += 1
        dropped[reason] += 1

    def _log_rejection_summary(self, scope: str, dropped: Counter[str]) -> None:
        if not dropped:
            return

        summary = dict(sorted(dropped.items()))
        self._logger.warning(
            "Dropped vendor payloads: venue=%s scope=%s details=%s",
            self._venue,
            scope,
            summary,
        )

    @staticmethod
    def _normalize_resolution(resolution: str) -> str:
        return resolution if resolution in {"1m", "5m", "1h", "1d"} else "1h"

    @staticmethod
    def _bound_event_time(ts_event: datetime, ts_record: datetime) -> datetime:
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
