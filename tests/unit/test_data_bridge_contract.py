"""Unit tests for the provider-neutral data-bridge contract (LA-019).

Tested components
-----------------
* :class:`~apps.data_collector.connectors.capabilities.VenueCapabilities`
* :class:`~apps.data_collector.connectors.data_bridge.ConnectorDataBridge`
* :exc:`~apps.data_collector.connectors.data_bridge.UnsupportedCapabilityError`
* :class:`~apps.data_collector.connectors.data_bridge.SnapshotWindow`
* :class:`~apps.data_collector.connectors.data_bridge.IncrementalCursor`
* :class:`~apps.data_collector.connectors.data_bridge.StreamTopic`
* :class:`~apps.data_collector.connectors.factory.VenueConnectorFactory`
  ``create_data_bridge`` method

All tests use an in-process stub adapter — no network calls are made.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import pytest
from apps.data_collector.connectors.capabilities import VenueCapabilities
from apps.data_collector.connectors.data_bridge import (
    ConnectorDataBridge,
    DataBridgeProtocol,
    IncrementalCursor,
    SnapshotWindow,
    StreamTopic,
    UnsupportedCapabilityError,
)

import alpha_core.adapters.base as adapters_base
import alpha_core.events.models as event_models
import alpha_core.instruments.models as instrument_models

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_BASE_TIME = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def _trade(instrument_id: str, ts_offset_seconds: int = 0) -> event_models.CanonicalTrade:
    ts = _BASE_TIME + timedelta(seconds=ts_offset_seconds)
    return event_models.CanonicalTrade(  # type: ignore[call-arg]
        venue_id="stub",
        instrument_id=instrument_id,
        ts_event=ts,
        ts_record=ts,
        price=Decimal("0.55"),
        size=Decimal("10"),
        side=event_models.TradeSide.BUY,
        trade_id=f"trade-{ts_offset_seconds}",
    )


def _book(instrument_id: str) -> event_models.CanonicalBookSnapshot:
    return event_models.CanonicalBookSnapshot(  # type: ignore[call-arg]
        venue_id="stub",
        instrument_id=instrument_id,
        ts_event=_BASE_TIME,
        ts_record=_BASE_TIME,
        bids=[],
        asks=[],
    )


def _ohlcv(
    instrument_id: str, resolution: Literal["1m", "5m", "1h", "1d"] = "1h"
) -> event_models.CanonicalOHLCV:
    return event_models.CanonicalOHLCV(  # type: ignore[call-arg]
        venue_id="stub",
        instrument_id=instrument_id,
        ts_event=_BASE_TIME,
        ts_record=_BASE_TIME,
        open=Decimal("0.40"),
        high=Decimal("0.60"),
        low=Decimal("0.35"),
        close=Decimal("0.50"),
        volume=Decimal("500"),
        resolution=resolution,
    )


class _StubAdapter(adapters_base.VenueAdapter):
    """Minimal synchronous stub — returns canned data."""

    def __init__(
        self,
        *,
        name: str = "stub",
        trades_by_id: dict[str, list[event_models.CanonicalTrade]] | None = None,
        book_by_id: dict[str, event_models.CanonicalBookSnapshot] | None = None,
        ohlcv_by_id: dict[str, list[event_models.CanonicalOHLCV]] | None = None,
    ) -> None:
        self._name = name
        self._trades = trades_by_id or {}
        self._books = book_by_id or {}
        self._ohlcv = ohlcv_by_id or {}

    def venue_name(self) -> str:
        return self._name

    async def fetch_trades(
        self,
        outcome_id: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[event_models.CanonicalTrade]:
        rows = self._trades.get(outcome_id, [])
        if since is not None:
            rows = [r for r in rows if r.ts_event >= since]
        return rows[:limit]

    async def fetch_order_book(self, outcome_id: str) -> event_models.CanonicalBookSnapshot:
        if outcome_id not in self._books:
            raise KeyError(f"No book for {outcome_id}")
        return self._books[outcome_id]

    async def fetch_ohlcv(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> list[event_models.CanonicalOHLCV]:
        return self._ohlcv.get(outcome_id, [])[:limit]

    async def fetch_markets(self) -> list[instrument_models.MarketSpec]:
        return []

    async def fetch_markets_with_raw(
        self,
    ) -> tuple[list[instrument_models.MarketSpec], list[object]]:
        return [], []

    async def fetch_trades_with_raw(
        self, outcome_id: str, since: datetime | None = None, limit: int = 100
    ) -> tuple[list[event_models.CanonicalTrade], list[object]]:
        return await self.fetch_trades(outcome_id, since=since, limit=limit), []

    async def fetch_order_book_with_raw(
        self, outcome_id: str
    ) -> tuple[event_models.CanonicalBookSnapshot, object]:
        return await self.fetch_order_book(outcome_id), {}

    async def fetch_ohlcv_with_raw(
        self, outcome_id: str, resolution: str = "1h", limit: int = 100
    ) -> tuple[list[event_models.CanonicalOHLCV], list[object]]:
        return await self.fetch_ohlcv(outcome_id, resolution=resolution, limit=limit), []


class _HistoricalBookAdapter(_StubAdapter):
    async def fetch_order_book_snapshot_at(
        self,
        outcome_id: str,
        *,
        as_of: datetime,
    ) -> event_models.CanonicalBookSnapshot:
        del as_of
        return await self.fetch_order_book(outcome_id)


class _HistoricalOHLCVAdapter(_StubAdapter):
    async def fetch_ohlcv_window(
        self,
        outcome_id: str,
        *,
        start: datetime,
        end: datetime,
        resolution: str,
        limit: int,
    ) -> list[event_models.CanonicalOHLCV]:
        rows = await self.fetch_ohlcv(outcome_id, resolution=resolution, limit=limit)
        return [row for row in rows if start <= row.ts_event <= end]


class _HistoricalMarketDataAdapter(_HistoricalBookAdapter, _HistoricalOHLCVAdapter):
    pass


def _make_bridge(
    *,
    venue_name: str = "stub",
    trades_by_id: dict[str, list[event_models.CanonicalTrade]] | None = None,
    book_by_id: dict[str, event_models.CanonicalBookSnapshot] | None = None,
    ohlcv_by_id: dict[str, list[event_models.CanonicalOHLCV]] | None = None,
    historical_books: bool = False,
    historical_ohlcv: bool = False,
    capabilities_override: VenueCapabilities | None = None,
) -> ConnectorDataBridge:
    adapter_cls: type[_StubAdapter]
    if historical_books and historical_ohlcv:
        adapter_cls = _HistoricalMarketDataAdapter
    elif historical_books:
        adapter_cls = _HistoricalBookAdapter
    elif historical_ohlcv:
        adapter_cls = _HistoricalOHLCVAdapter
    else:
        adapter_cls = _StubAdapter
    adapter = adapter_cls(
        name=venue_name,
        trades_by_id=trades_by_id,
        book_by_id=book_by_id,
        ohlcv_by_id=ohlcv_by_id,
    )
    return ConnectorDataBridge(adapter, capabilities_override=capabilities_override)


# ---------------------------------------------------------------------------
# 1. VenueCapabilities model
# ---------------------------------------------------------------------------


class TestVenueCapabilities:
    def test_default_values(self) -> None:
        caps = VenueCapabilities(venue_name="test")
        assert caps.trades is True
        assert caps.book_snapshots is True
        assert caps.book_deltas is False
        assert caps.streaming_trades is False
        assert caps.streaming_books is False
        assert caps.sequence_id_capable is False

    def test_supports_ohlcv_resolution_present(self) -> None:
        caps = VenueCapabilities(venue_name="test", ohlcv_resolutions=["1m", "1h"])
        assert caps.supports_ohlcv("1h") is True
        assert caps.supports_ohlcv("1d") is False

    def test_supports_streaming_when_any_channel_declared(self) -> None:
        caps = VenueCapabilities(venue_name="test", streaming_trades=True)
        assert caps.supports_streaming() is True

    def test_supports_streaming_false_when_neither_declared(self) -> None:
        caps = VenueCapabilities(venue_name="test")
        assert caps.supports_streaming() is False

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(Exception):
            VenueCapabilities(venue_name="test", unknown_field=True)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# 2. UnsupportedCapabilityError
# ---------------------------------------------------------------------------


class TestUnsupportedCapabilityError:
    def test_attributes_set(self) -> None:
        err = UnsupportedCapabilityError("streaming", "my_venue")
        assert err.capability == "streaming"
        assert err.venue_name == "my_venue"

    def test_is_runtime_error(self) -> None:
        err = UnsupportedCapabilityError("trades", "venue_x")
        assert isinstance(err, RuntimeError)

    def test_message_contains_component(self) -> None:
        err = UnsupportedCapabilityError("ohlcv_resolutions['5d']", "venue_x")
        assert "ohlcv_resolutions" in str(err)
        assert "venue_x" in str(err)


# ---------------------------------------------------------------------------
# 3. SnapshotWindow / IncrementalCursor / StreamTopic dataclasses
# ---------------------------------------------------------------------------


class TestDomainDataclasses:
    def test_snapshot_window_frozen(self) -> None:
        win = SnapshotWindow(
            start=_BASE_TIME,
            end=_BASE_TIME + timedelta(hours=1),
        )
        with pytest.raises(Exception):
            win.start = _BASE_TIME + timedelta(hours=2)  # type: ignore[misc]

    def test_snapshot_window_defaults(self) -> None:
        win = SnapshotWindow(start=_BASE_TIME, end=_BASE_TIME + timedelta(hours=1))
        assert win.event_types == [event_models.EventType.TRADE]
        assert win.instrument_ids == []
        assert win.ohlcv_resolution == "1h"
        assert win.limit_per_instrument == 500

    def test_incremental_cursor_defaults(self) -> None:
        cur = IncrementalCursor(venue_name="v", instrument_ids=["x"])
        assert cur.cursor_type == "ts_event"
        assert cur.resume_safe is True
        assert cur.cursor_watermark_utc == datetime(1970, 1, 1, tzinfo=UTC)

    def test_stream_topic_defaults(self) -> None:
        topic = StreamTopic(instrument_id="abc")
        assert topic.event_type == event_models.EventType.TRADE


# ---------------------------------------------------------------------------
# 4. DataBridgeProtocol structural sub-typing
# ---------------------------------------------------------------------------


class TestDataBridgeProtocol:
    def test_connector_data_bridge_satisfies_protocol(self) -> None:
        bridge = _make_bridge()
        assert isinstance(bridge, DataBridgeProtocol)

    def test_venue_name_property(self) -> None:
        bridge = _make_bridge(venue_name="kalshi")
        assert bridge.venue_name == "kalshi"

    def test_capabilities_returns_venue_capabilities(self) -> None:
        bridge = _make_bridge()
        caps = bridge.capabilities()
        assert isinstance(caps, VenueCapabilities)
        assert caps.venue_name == "stub"


# ---------------------------------------------------------------------------
# 5. pull_snapshot
# ---------------------------------------------------------------------------


class TestPullSnapshot:
    def test_trades_within_window_returned(self) -> None:
        t1 = _trade("mkt:a:yes", ts_offset_seconds=0)
        t2 = _trade("mkt:a:yes", ts_offset_seconds=3600)
        bridge = _make_bridge(trades_by_id={"mkt:a:yes": [t1, t2]})
        win = SnapshotWindow(
            start=_BASE_TIME - timedelta(seconds=1),
            end=_BASE_TIME + timedelta(hours=1),
            instrument_ids=["mkt:a:yes"],
        )
        events = asyncio.run(bridge.pull_snapshot(win))
        assert len(events) == 2

    def test_trades_outside_window_excluded(self) -> None:
        before = _trade("mkt:a:yes", ts_offset_seconds=-100)
        inside = _trade("mkt:a:yes", ts_offset_seconds=0)
        bridge = _make_bridge(trades_by_id={"mkt:a:yes": [before, inside]})
        win = SnapshotWindow(
            start=_BASE_TIME,
            end=_BASE_TIME + timedelta(hours=1),
            instrument_ids=["mkt:a:yes"],
        )
        events = asyncio.run(bridge.pull_snapshot(win))
        assert all(e.ts_event >= win.start for e in events)

    def test_trade_snapshot_paginates_until_window_exhausted(self) -> None:
        iid = "mkt:a:yes"
        trades = [_trade(iid, ts_offset_seconds=index * 60) for index in range(3)]
        bridge = _make_bridge(trades_by_id={iid: trades})
        win = SnapshotWindow(
            start=_BASE_TIME - timedelta(seconds=1),
            end=_BASE_TIME + timedelta(minutes=5),
            instrument_ids=[iid],
            limit_per_instrument=2,
        )
        events = asyncio.run(bridge.pull_snapshot(win))
        assert [event.trade_id for event in events] == ["trade-0", "trade-60", "trade-120"]  # type: ignore[attr-defined]

    def test_ohlcv_snapshot_returns_ohlcv_events(self) -> None:
        ohlcv = _ohlcv("mkt:b:yes", resolution="1h")
        bridge = _make_bridge(
            ohlcv_by_id={"mkt:b:yes": [ohlcv]},
            historical_ohlcv=True,
        )
        win = SnapshotWindow(
            start=_BASE_TIME - timedelta(seconds=1),
            end=_BASE_TIME + timedelta(hours=1),
            instrument_ids=["mkt:b:yes"],
            event_types=[event_models.EventType.OHLCV],
            ohlcv_resolution="1h",
        )
        events = asyncio.run(bridge.pull_snapshot(win))
        assert len(events) == 1
        assert isinstance(events[0], event_models.CanonicalOHLCV)

    def test_book_snapshot_included(self) -> None:
        book = _book("mkt:c:yes")
        bridge = _make_bridge(
            book_by_id={"mkt:c:yes": book},
            historical_books=True,
        )
        win = SnapshotWindow(
            start=_BASE_TIME - timedelta(seconds=1),
            end=_BASE_TIME + timedelta(hours=1),
            instrument_ids=["mkt:c:yes"],
            event_types=[event_models.EventType.BOOK_SNAPSHOT],
        )
        events = asyncio.run(bridge.pull_snapshot(win))
        assert len(events) == 1
        assert isinstance(events[0], event_models.CanonicalBookSnapshot)

    def test_events_sorted_by_ts_event(self) -> None:
        iid = "mkt:d:yes"
        trades = [_trade(iid, ts_offset_seconds=i * 10) for i in range(5, 0, -1)]
        bridge = _make_bridge(trades_by_id={iid: trades})
        win = SnapshotWindow(
            start=_BASE_TIME - timedelta(seconds=1),
            end=_BASE_TIME + timedelta(minutes=10),
            instrument_ids=[iid],
        )
        events = asyncio.run(bridge.pull_snapshot(win))
        ts_list = [e.ts_event for e in events]
        assert ts_list == sorted(ts_list)

    def test_trades_not_supported_raises(self) -> None:
        caps = VenueCapabilities(venue_name="stub", trades=False)
        bridge = _make_bridge(capabilities_override=caps)
        win = SnapshotWindow(
            start=_BASE_TIME,
            end=_BASE_TIME + timedelta(hours=1),
            instrument_ids=["mkt:e:yes"],
        )
        with pytest.raises(UnsupportedCapabilityError) as exc_info:
            asyncio.run(bridge.pull_snapshot(win))
        assert exc_info.value.capability == "trades"

    def test_ohlcv_resolution_not_supported_raises(self) -> None:
        caps = VenueCapabilities(venue_name="stub", ohlcv_resolutions=["1h"])
        bridge = _make_bridge(capabilities_override=caps)
        win = SnapshotWindow(
            start=_BASE_TIME,
            end=_BASE_TIME + timedelta(hours=1),
            instrument_ids=["mkt:f:yes"],
            event_types=[event_models.EventType.OHLCV],
            ohlcv_resolution="5d",  # not in list
        )
        with pytest.raises(UnsupportedCapabilityError):
            asyncio.run(bridge.pull_snapshot(win))

    def test_empty_instrument_ids_returns_empty(self) -> None:
        bridge = _make_bridge()
        win = SnapshotWindow(
            start=_BASE_TIME,
            end=_BASE_TIME + timedelta(hours=1),
            instrument_ids=[],
        )
        events = asyncio.run(bridge.pull_snapshot(win))
        assert events == []

    def test_book_snapshot_without_historical_method_raises(self) -> None:
        bridge = _make_bridge(book_by_id={})
        win = SnapshotWindow(
            start=_BASE_TIME - timedelta(seconds=1),
            end=_BASE_TIME + timedelta(hours=1),
            instrument_ids=["mkt:missing:yes"],
            event_types=[event_models.EventType.BOOK_SNAPSHOT],
        )
        with pytest.raises(UnsupportedCapabilityError) as exc_info:
            asyncio.run(bridge.pull_snapshot(win))
        assert exc_info.value.capability == "book_snapshots"

    def test_ohlcv_snapshot_without_historical_method_raises(self) -> None:
        bridge = _make_bridge(ohlcv_by_id={"mkt:b:yes": [_ohlcv("mkt:b:yes")]})
        win = SnapshotWindow(
            start=_BASE_TIME - timedelta(seconds=1),
            end=_BASE_TIME + timedelta(hours=1),
            instrument_ids=["mkt:b:yes"],
            event_types=[event_models.EventType.OHLCV],
            ohlcv_resolution="1h",
        )
        with pytest.raises(UnsupportedCapabilityError) as exc_info:
            asyncio.run(bridge.pull_snapshot(win))
        assert exc_info.value.capability == "ohlcv_resolutions['1h']"


# ---------------------------------------------------------------------------
# 6. pull_incremental
# ---------------------------------------------------------------------------


class TestPullIncremental:
    def test_returns_events_after_watermark(self) -> None:
        iid = "mkt:g:yes"
        t_old = _trade(iid, ts_offset_seconds=-60)
        t_new = _trade(iid, ts_offset_seconds=60)
        bridge = _make_bridge(trades_by_id={iid: [t_old, t_new]})
        cursor = IncrementalCursor(
            venue_name="stub",
            instrument_ids=[iid],
            cursor_watermark_utc=_BASE_TIME,  # only ts_event >= _BASE_TIME kept
        )
        events, _new_cursor = asyncio.run(bridge.pull_incremental(cursor))
        assert len(events) == 1
        assert events[0].ts_event == _BASE_TIME + timedelta(seconds=60)

    def test_updated_cursor_watermark_is_max_ts(self) -> None:
        iid = "mkt:h:yes"
        trades = [_trade(iid, ts_offset_seconds=i * 30) for i in range(3)]
        bridge = _make_bridge(trades_by_id={iid: trades})
        cursor = IncrementalCursor(
            venue_name="stub",
            instrument_ids=[iid],
            cursor_watermark_utc=_BASE_TIME - timedelta(seconds=1),
        )
        _, new_cursor = asyncio.run(bridge.pull_incremental(cursor))
        expected = _BASE_TIME + timedelta(seconds=60)
        assert new_cursor.cursor_watermark_utc == expected
        assert new_cursor.resume_safe is True

    def test_no_new_events_returns_original_cursor(self) -> None:
        iid = "mkt:i:yes"
        bridge = _make_bridge(trades_by_id={iid: []})
        cursor = IncrementalCursor(
            venue_name="stub",
            instrument_ids=[iid],
            cursor_watermark_utc=_BASE_TIME,
        )
        events, returned_cursor = asyncio.run(bridge.pull_incremental(cursor))
        assert events == []
        assert returned_cursor is cursor

    def test_trades_not_supported_raises(self) -> None:
        caps = VenueCapabilities(venue_name="stub", trades=False)
        bridge = _make_bridge(capabilities_override=caps)
        cursor = IncrementalCursor(venue_name="stub", instrument_ids=["x"])
        with pytest.raises(UnsupportedCapabilityError):
            asyncio.run(bridge.pull_incremental(cursor))

    def test_cursor_value_contains_iso_timestamp(self) -> None:
        iid = "mkt:j:yes"
        trades = [_trade(iid, ts_offset_seconds=0)]
        bridge = _make_bridge(trades_by_id={iid: trades})
        cursor = IncrementalCursor(
            venue_name="stub",
            instrument_ids=[iid],
            cursor_watermark_utc=_BASE_TIME - timedelta(seconds=1),
        )
        _, new_cursor = asyncio.run(bridge.pull_incremental(cursor))
        payload = json.loads(new_cursor.cursor_value)
        assert payload["cursor_type"] == "trade_id"
        assert payload["watermark_utc"] == _BASE_TIME.isoformat()
        assert payload["seen"] == ["trade-0"]

    def test_resume_deduplicates_same_watermark_trade_ids(self) -> None:
        iid = "mkt:k:yes"
        initial_bridge = _make_bridge(trades_by_id={iid: [_trade(iid, ts_offset_seconds=0)]})
        start_cursor = IncrementalCursor(
            venue_name="stub",
            instrument_ids=[iid],
            cursor_watermark_utc=_BASE_TIME - timedelta(seconds=1),
        )
        _, resume_cursor = asyncio.run(initial_bridge.pull_incremental(start_cursor))

        resumed_bridge = _make_bridge(
            trades_by_id={
                iid: [
                    _trade(iid, ts_offset_seconds=0),
                    event_models.CanonicalTrade(  # type: ignore[call-arg]
                        venue_id="stub",
                        instrument_id=iid,
                        ts_event=_BASE_TIME,
                        ts_record=_BASE_TIME,
                        price=Decimal("0.56"),
                        size=Decimal("9"),
                        side=event_models.TradeSide.BUY,
                        trade_id="trade-late-at-watermark",
                    ),
                    _trade(iid, ts_offset_seconds=60),
                ]
            }
        )

        events, new_cursor = asyncio.run(resumed_bridge.pull_incremental(resume_cursor))

        trade_ids = [
            event.trade_id for event in events if isinstance(event, event_models.CanonicalTrade)
        ]
        assert trade_ids == [
            "trade-late-at-watermark",
            "trade-60",
        ]
        assert new_cursor.cursor_watermark_utc == _BASE_TIME + timedelta(seconds=60)


# ---------------------------------------------------------------------------
# 7. stream_subscribe
# ---------------------------------------------------------------------------


class TestStreamSubscribe:
    def test_raises_when_streaming_not_supported(self) -> None:
        caps = VenueCapabilities(venue_name="stub", streaming_trades=False, streaming_books=False)
        bridge = _make_bridge(capabilities_override=caps)
        with pytest.raises(UnsupportedCapabilityError) as exc_info:
            bridge.stream_subscribe([StreamTopic(instrument_id="mkt:k:yes")])
        assert exc_info.value.capability == "streaming"
        assert exc_info.value.venue_name == "stub"

    def test_returns_async_iterator_when_supported(self) -> None:
        """Adapter with watch_trades method → stream_subscribe returns an iterator."""
        # Attach a watch_trades method duck-style
        adapter = _StubAdapter(name="streaming_venue")

        async def _watch(iid: str) -> Any:
            yield []
            return

        adapter.watch_trades = _watch  # type: ignore[attr-defined]
        caps = VenueCapabilities(
            venue_name="streaming_venue",
            streaming_trades=True,
        )
        bridge = ConnectorDataBridge(adapter, capabilities_override=caps)
        result = bridge.stream_subscribe([StreamTopic(instrument_id="mkt:l:yes")])
        # Should be an async iterator (has __aiter__)
        assert hasattr(result, "__aiter__")


# ---------------------------------------------------------------------------
# 8. Capability inference from adapter duck-typing
# ---------------------------------------------------------------------------


class TestCapabilityInference:
    def test_no_watch_methods_infers_no_streaming(self) -> None:
        bridge = _make_bridge(venue_name="no_stream")
        caps = bridge.capabilities()
        assert caps.streaming_trades is False
        assert caps.streaming_books is False
        assert caps.book_snapshots is False
        assert caps.ohlcv_resolutions == []

    def test_watch_trades_infers_streaming_trades(self) -> None:
        adapter = _StubAdapter(name="stream_venue")

        async def _watch(iid: str) -> Any:
            return
            yield

        adapter.watch_trades = _watch  # type: ignore[attr-defined]
        bridge = ConnectorDataBridge(adapter)  # no override → inferred
        assert bridge.capabilities().streaming_trades is True

    def test_watch_order_book_infers_streaming_books(self) -> None:
        adapter = _StubAdapter(name="stream_venue2")

        async def _watch(iid: str) -> Any:
            return
            yield

        adapter.watch_order_book = _watch  # type: ignore[attr-defined]
        bridge = ConnectorDataBridge(adapter)
        assert bridge.capabilities().streaming_books is True

    def test_historical_book_method_infers_snapshot_support(self) -> None:
        bridge = _make_bridge(venue_name="history_books", historical_books=True)
        assert bridge.capabilities().book_snapshots is True

    def test_historical_ohlcv_method_infers_ohlcv_support(self) -> None:
        bridge = _make_bridge(venue_name="history_ohlcv", historical_ohlcv=True)
        assert bridge.capabilities().supports_ohlcv("1h") is True


# ---------------------------------------------------------------------------
# 9. VenueConnectorFactory.create_data_bridge
# ---------------------------------------------------------------------------


class TestFactoryCreateDataBridge:
    def _make_factory(self, mode: Literal["poll", "stream", "both"] = "poll") -> Any:
        """Build a minimal factory instance without real config."""
        from unittest.mock import MagicMock

        from apps.data_collector.connectors.factory import VenueConnectorFactory

        import alpha_core.config.models as config_models

        venue_cfg = config_models.VenueConfig(
            name="stub_venue",
            exchange_class="stub.StubAdapter",
            collection=config_models.CollectionConfig(mode=mode),
        )
        factory = VenueConnectorFactory.__new__(VenueConnectorFactory)
        factory._venue_map = {"stub_venue": venue_cfg}
        factory._market_master = MagicMock()
        factory._market_master_snapshot_path = MagicMock()
        factory._market_master_snapshot_path.exists = lambda: False
        return factory

    def test_returns_connector_data_bridge(self) -> None:
        from apps.data_collector.connectors.data_bridge import ConnectorDataBridge

        factory = self._make_factory()
        adapter = _StubAdapter(name="stub_venue")
        bridge = factory.create_data_bridge(adapter)
        assert isinstance(bridge, ConnectorDataBridge)

    def test_bridge_has_correct_venue_name(self) -> None:
        factory = self._make_factory()
        adapter = _StubAdapter(name="stub_venue")
        bridge = factory.create_data_bridge(adapter)
        assert bridge.venue_name == "stub_venue"

    def test_historical_snapshot_capabilities_require_dedicated_methods(self) -> None:
        factory = self._make_factory()
        adapter = _StubAdapter(name="stub_venue")
        bridge = factory.create_data_bridge(adapter)
        assert bridge.capabilities().book_snapshots is False
        assert bridge.capabilities().ohlcv_resolutions == []

    def test_streaming_false_when_poll_mode(self) -> None:
        factory = self._make_factory(mode="poll")
        adapter = _StubAdapter(name="stub_venue")

        async def _watch(iid: str) -> Any:
            return
            yield

        adapter.watch_trades = _watch  # type: ignore[attr-defined]
        bridge = factory.create_data_bridge(adapter)
        # poll mode → streaming should be disabled even if adapter has watch_trades
        assert bridge.capabilities().streaming_trades is False

    def test_streaming_true_when_stream_mode_and_adapter_supports(self) -> None:
        factory = self._make_factory(mode="stream")
        adapter = _StubAdapter(name="stub_venue")

        async def _watch(iid: str) -> Any:
            return
            yield

        adapter.watch_trades = _watch  # type: ignore[attr-defined]
        bridge = factory.create_data_bridge(adapter)
        assert bridge.capabilities().streaming_trades is True

    def test_capabilities_override_preserved(self) -> None:
        factory = self._make_factory(mode="poll")
        adapter = _StubAdapter(name="stub_venue")
        override = VenueCapabilities(
            venue_name="stub_venue",
            streaming_trades=True,
            sequence_id_capable=True,
        )
        bridge = factory.create_data_bridge(adapter, capabilities_override=override)
        assert bridge.capabilities().sequence_id_capable is True
        assert bridge.capabilities().streaming_trades is True
