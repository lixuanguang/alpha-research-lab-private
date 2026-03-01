"""pmxt-backed venue adapter implementation."""

from __future__ import annotations

import importlib
import inspect
import logging
from collections import Counter
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import ValidationError

import alpha_core.adapters.base as adapters_base
import alpha_core.adapters.pmxt_mapping as pmxt_mapping
import alpha_core.adapters.pmxt_parsing as pmxt_parsing
import alpha_core.adapters.venue_configs as venue_configs
import alpha_core.config.models as config_models
import alpha_core.config.secrets as secrets
import alpha_core.events.models as event_models
import alpha_core.events.schema_version as event_schema_version
import alpha_core.instruments.models as instrument_models

try:
    pmxt_module = cast(Any, importlib.import_module("pmxt"))
except ImportError:  # pragma: no cover
    pmxt_module = None


class PmxtAdapter(adapters_base.VenueAdapter):
    """Maps pmxt exchange responses into canonical alpha-core models."""

    def __init__(self, exchange_name: str, config: config_models.VenueConfig) -> None:
        if pmxt_module is None:
            raise ImportError("pmxt is required for PmxtAdapter")

        self._venue = venue_configs.normalize_venue_name(exchange_name)
        self._quirks = venue_configs.get_venue_quirks(self._venue)
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
        markets, _ = await self.fetch_markets_with_raw()
        return markets

    async def fetch_markets_with_raw(
        self,
    ) -> tuple[list[instrument_models.MarketSpec], list[object]]:
        raw_markets = cast(list[object], await self._invoke_exchange("fetch_markets"))
        self._outcome_market_index.clear()

        dropped: Counter[str] = Counter()
        mapped_markets: list[instrument_models.MarketSpec] = []
        for raw_market in raw_markets:
            try:
                market = pmxt_mapping.map_market(raw_market, venue=self._venue)
            except (TypeError, ValueError, ValidationError):
                self._record_rejection_count("markets", "invalid_payload", 1, dropped)
                continue

            for outcome in market.outcomes:
                market_ids = self._outcome_market_index.setdefault(outcome.outcome_id, set())
                market_ids.add(market.market_id)
            mapped_markets.append(market)

        self._log_rejection_summary("markets", dropped)
        return mapped_markets, raw_markets

    async def fetch_trades(
        self,
        outcome_id: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[event_models.CanonicalTrade]:
        trades, _ = await self.fetch_trades_with_raw(
            outcome_id,
            since=since,
            limit=limit,
        )
        return trades

    async def fetch_trades_with_raw(
        self,
        outcome_id: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> tuple[list[event_models.CanonicalTrade], list[object]]:
        instrument_id = self._instrument_id(outcome_id)
        raw_trades = cast(
            list[object],
            await self._invoke_exchange(
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
                mapped.append(
                    pmxt_mapping.map_trade(
                        raw_trade,
                        venue=self._venue,
                        instrument_id=instrument_id,
                        quirks=self._quirks,
                    )
                )
            except (TypeError, ValueError, ValidationError):
                self._record_rejection_count("trades", "invalid_payload", 1, dropped)
                continue

        self._log_rejection_summary("trades", dropped)
        return mapped, raw_trades

    async def fetch_order_book(self, outcome_id: str) -> event_models.CanonicalBookSnapshot:
        book, _ = await self.fetch_order_book_with_raw(outcome_id)
        return book

    async def fetch_order_book_with_raw(
        self,
        outcome_id: str,
    ) -> tuple[event_models.CanonicalBookSnapshot, object]:
        instrument_id = self._instrument_id(outcome_id)
        raw_book = await self._invoke_exchange("fetch_order_book", outcome_id)
        dropped: Counter[str] = Counter()

        try:
            book = self._map_order_book_payload(
                raw_book,
                instrument_id=instrument_id,
                scope="book",
                dropped=dropped,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            self._record_rejection_count("book", "invalid_payload", 1, dropped)
            self._log_rejection_summary("book", dropped)
            raise ValueError(
                f"Invalid order book payload for venue `{self._venue}` and outcome `{outcome_id}`"
            ) from exc
        self._log_rejection_summary("book", dropped)
        return book, raw_book

    async def fetch_ohlcv(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> list[event_models.CanonicalOHLCV]:
        candles, _ = await self.fetch_ohlcv_with_raw(
            outcome_id,
            resolution=resolution,
            limit=limit,
        )
        return candles

    async def fetch_ohlcv_with_raw(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> tuple[list[event_models.CanonicalOHLCV], list[object]]:
        raw_ohlcv = cast(
            list[object],
            await self._invoke_exchange(
                "fetch_ohlcv",
                outcome_id,
                resolution=resolution,
                limit=limit,
            ),
        )

        instrument_id = self._instrument_id(outcome_id)
        normalized_resolution = pmxt_parsing.normalize_resolution(resolution)
        dropped: Counter[str] = Counter()
        mapped: list[event_models.CanonicalOHLCV] = []

        for candle in raw_ohlcv:
            ts_record = datetime.now(tz=UTC)
            parsed = pmxt_mapping.parse_ohlcv(candle, quirks=self._quirks)
            if parsed is None:
                self._record_rejection_count("ohlcv", "invalid_payload", 1, dropped)
                continue

            ts_event, open_price, high_price, low_price, close_price, volume = parsed
            payload: dict[str, Any] = {
                "instrument_id": instrument_id,
                "venue_id": self._venue,
                "event_type": event_models.EventType.OHLCV,
                "ts_event": pmxt_parsing.bound_event_time(ts_event=ts_event, ts_record=ts_record),
                "ts_record": ts_record,
                "schema_version": event_schema_version.CANONICAL_EVENT_SCHEMA_VERSION,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
                "resolution": normalized_resolution,
            }
            try:
                mapped.append(event_models.CanonicalOHLCV.model_validate(payload))
            except ValidationError:
                self._record_rejection_count("ohlcv", "invalid_event", 1, dropped)

        self._log_rejection_summary("ohlcv", dropped)
        return mapped, raw_ohlcv

    def watch_trades(self, outcome_id: str) -> AsyncIterator[list[event_models.CanonicalTrade]]:
        """Stream canonical trade batches from the venue watch feed."""
        instrument_id = self._instrument_id(outcome_id)

        async def _stream() -> AsyncIterator[list[event_models.CanonicalTrade]]:
            raw_stream = self._invoke_exchange_stream("watch_trades", outcome_id)
            async for raw_batch in raw_stream:
                batch = raw_batch if isinstance(raw_batch, list) else [raw_batch]
                dropped: Counter[str] = Counter()
                mapped_batch: list[event_models.CanonicalTrade] = []
                for raw_trade in batch:
                    try:
                        mapped_batch.append(
                            pmxt_mapping.map_trade(
                                raw_trade,
                                venue=self._venue,
                                instrument_id=instrument_id,
                                quirks=self._quirks,
                            )
                        )
                    except (TypeError, ValueError, ValidationError):
                        self._record_rejection_count("watch_trades", "invalid_payload", 1, dropped)
                self._log_rejection_summary("watch_trades", dropped)
                if mapped_batch:
                    yield mapped_batch

        return _stream()

    def watch_order_book(
        self,
        outcome_id: str,
    ) -> AsyncIterator[event_models.CanonicalBookSnapshot]:
        """Stream canonical order book snapshots from the venue watch feed."""
        instrument_id = self._instrument_id(outcome_id)

        async def _stream() -> AsyncIterator[event_models.CanonicalBookSnapshot]:
            raw_stream = self._invoke_exchange_stream("watch_order_book", outcome_id)
            async for raw_book in raw_stream:
                dropped: Counter[str] = Counter()
                try:
                    mapped = self._map_order_book_payload(
                        raw_book,
                        instrument_id=instrument_id,
                        scope="watch_order_book",
                        dropped=dropped,
                    )
                except (TypeError, ValueError, ValidationError):
                    self._record_rejection_count("watch_order_book", "invalid_payload", 1, dropped)
                    self._log_rejection_summary("watch_order_book", dropped)
                    continue
                self._log_rejection_summary("watch_order_book", dropped)
                yield mapped

        return _stream()

    def _instrument_id(self, outcome_id: str) -> str:
        return pmxt_mapping.resolve_instrument_id(
            outcome_id,
            venue=self._venue,
            outcome_market_index=self._outcome_market_index,
        )

    async def _invoke_exchange(self, method_name: str, *args: object, **kwargs: object) -> object:
        method = getattr(self._exchange, method_name)
        result: object
        if not kwargs:
            result = method(*args)
        else:
            result = method(*args, **pmxt_parsing.supported_kwargs(method, kwargs))
        if inspect.isawaitable(result):
            return await result
        return result

    def _invoke_exchange_stream(
        self,
        method_name: str,
        *args: object,
        **kwargs: object,
    ) -> AsyncIterator[object]:
        method = getattr(self._exchange, method_name)
        if not kwargs:
            result = method(*args)
        else:
            result = method(*args, **pmxt_parsing.supported_kwargs(method, kwargs))
        if inspect.isawaitable(result):
            raise TypeError(
                f"Expected async iterator from `{method_name}`, received awaitable `{type(result)}`"
            )
        if not hasattr(result, "__aiter__"):
            raise TypeError(
                f"Expected async iterator from `{method_name}`, got `{type(result).__name__}`"
            )
        return cast(AsyncIterator[object], result)

    def _map_order_book_payload(
        self,
        raw_book: object,
        *,
        instrument_id: str,
        scope: str,
        dropped: Counter[str],
    ) -> event_models.CanonicalBookSnapshot:
        ts_record = datetime.now(tz=UTC)
        ts_event = pmxt_parsing.coerce_event_time(
            pmxt_parsing.pick(raw_book, "timestamp", "ts", "time", default=ts_record),
            fallback=ts_record,
        )
        if ts_event is None:
            ts_event = ts_record

        raw_bids = pmxt_parsing.pick(raw_book, "bids", default=None)
        raw_asks = pmxt_parsing.pick(raw_book, "asks", default=None)
        if not isinstance(raw_bids, list) or not isinstance(raw_asks, list):
            raise ValueError("order book payload must contain list fields `bids` and `asks`")

        payload: dict[str, Any] = {
            "instrument_id": instrument_id,
            "venue_id": self._venue,
            "event_type": event_models.EventType.BOOK_SNAPSHOT,
            "ts_event": pmxt_parsing.bound_event_time(ts_event=ts_event, ts_record=ts_record),
            "ts_record": ts_record,
            "schema_version": event_schema_version.CANONICAL_EVENT_SCHEMA_VERSION,
        }

        payload["bids"], bids_invalid = pmxt_mapping.map_book_levels(
            raw_bids,
            side="bids",
            quirks=self._quirks,
        )
        payload["asks"], asks_invalid = pmxt_mapping.map_book_levels(
            raw_asks,
            side="asks",
            quirks=self._quirks,
        )

        if bids_invalid:
            self._record_rejection_count(scope, "bids_invalid_level", bids_invalid, dropped)
        if asks_invalid:
            self._record_rejection_count(scope, "asks_invalid_level", asks_invalid, dropped)
        if not payload["bids"] and not payload["asks"] and (bids_invalid or asks_invalid):
            raise ValueError("order book payload contains no valid levels")

        return event_models.CanonicalBookSnapshot.model_validate(payload)

    def _record_rejection_count(
        self,
        scope: str,
        reason: str,
        count: int,
        dropped: Counter[str],
    ) -> None:
        if count <= 0:
            return
        key = f"{scope}.{reason}"
        self._rejection_counts[key] += count
        dropped[reason] += count

    def _log_rejection_summary(self, scope: str, dropped: Counter[str]) -> None:
        if not dropped:
            return

        self._logger.warning(
            "Dropped vendor payloads: venue=%s scope=%s details=%s",
            self._venue,
            scope,
            dict(sorted(dropped.items())),
        )
