"""Unit tests for data-collector runtime orchestration helpers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast

import apps.data_collector.connectors._polling as connector_polling
import apps.data_collector.connectors._types as connector_types
import apps.data_collector.connectors.rate_limiter as connector_rate_limiter
import apps.data_collector.pipeline as collector_pipeline
import apps.data_collector.runtime as collector_runtime
import pytest

import alpha_core.adapters.base as adapters_base
import alpha_core.config.models as config_models
import alpha_core.events.models as event_models
import alpha_core.instruments.models as instrument_models
import alpha_core.storage.lineage as storage_lineage


def _settings() -> config_models.Settings:
    return config_models.Settings.model_validate(
        {
            "project_name": "alpha-research-lab",
            "venues": [
                {
                    "name": "kalshi",
                    "exchange_class": "Kalshi",
                    "enabled": True,
                    "rate_limit_rpm": 120,
                },
                {
                    "name": "polymarket",
                    "exchange_class": "Polymarket",
                    "enabled": False,
                    "rate_limit_rpm": 120,
                },
            ],
            "storage": {
                "base_path": "/tmp/alpha-runtime-tests",
                "partition_by": ["venue", "date"],
            },
            "log_level": "INFO",
            "feature_flags": {},
        }
    )


def _market(market_id: str, outcome_ids: list[str]) -> instrument_models.MarketSpec:
    now = datetime.now(tz=UTC)
    return instrument_models.MarketSpec.model_validate(
        {
            "market_id": market_id,
            "venue": "kalshi",
            "title": "Market",
            "outcomes": [
                {
                    "outcome_id": outcome_id,
                    "label": outcome_id.upper(),
                    "canonical_id": f"kalshi:{market_id}:{outcome_id}",
                }
                for outcome_id in outcome_ids
            ],
            "first_seen": now,
            "last_updated": now,
        }
    )


class _StubAdapter(adapters_base.VenueAdapter):
    def __init__(self, venue_name: str) -> None:
        self._venue_name = venue_name

    def venue_name(self) -> str:
        return self._venue_name

    async def fetch_markets(self) -> list[instrument_models.MarketSpec]:
        return [_market("mkt-a", ["yes", "no"])]

    async def fetch_markets_with_raw(
        self,
    ) -> tuple[list[instrument_models.MarketSpec], list[object]]:
        markets = await self.fetch_markets()
        return markets, [market.model_dump(mode="json") for market in markets]

    async def fetch_trades(
        self,
        outcome_id: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[event_models.CanonicalTrade]:
        del outcome_id, since, limit
        return []

    async def fetch_order_book(self, outcome_id: str) -> event_models.CanonicalBookSnapshot:
        raise NotImplementedError(f"book polling not implemented in test adapter: {outcome_id}")

    async def fetch_ohlcv(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> list[event_models.CanonicalOHLCV]:
        del outcome_id, resolution, limit
        return []

    async def fetch_trades_with_raw(
        self,
        outcome_id: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> tuple[list[event_models.CanonicalTrade], list[object]]:
        del outcome_id, since, limit
        return [], []

    async def fetch_order_book_with_raw(
        self,
        outcome_id: str,
    ) -> tuple[event_models.CanonicalBookSnapshot, object]:
        raise NotImplementedError(f"book polling not implemented in test adapter: {outcome_id}")

    async def fetch_ohlcv_with_raw(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> tuple[list[event_models.CanonicalOHLCV], list[object]]:
        del outcome_id, resolution, limit
        return [], []


class _FakePipeline:
    def __init__(self, connector_id: str, interval_seconds: float, status: str) -> None:
        self.connector = _StubPollingConnector(
            "kalshi",
            connector_id,
            interval_seconds=interval_seconds,
        )
        self.connector_id = self.connector.connector_id
        self.interval_seconds = interval_seconds
        self.venue = self.connector.venue
        self._status = status

    async def execute(self) -> storage_lineage.IngestionRun:
        now = datetime.now(tz=UTC)
        return storage_lineage.IngestionRun.model_validate(
            {
                "run_id": f"run-{self.connector_id.replace(':', '-')}",
                "venue": "kalshi",
                "connector_type": "polling",
                "event_types": ["trades"],
                "started_at": now,
                "completed_at": now,
                "status": self._status,
                "counts": {},
                "errors": [] if self._status == "completed" else ["pipeline failed"],
                "schema_version": 1,
                "config_snapshot": {},
            }
        )


class _StubPollingConnector(connector_polling.PollingConnector):
    def __init__(self, venue: str, connector_id: str, interval_seconds: float) -> None:
        super().__init__(venue=venue, interval_seconds=interval_seconds)
        self._connector_id = connector_id

    @property
    def connector_id(self) -> str:
        return self._connector_id

    async def poll_once(self) -> connector_types.PollingBatch:
        raise AssertionError(
            "Runtime scheduler callback should execute pipeline, not poller directly"
        )


def _emit(messages: list[tuple[str, bool]], message: str, is_error: bool) -> None:
    messages.append((message, is_error))


def test_collect_outcome_ids_deduplicates_and_caps() -> None:
    markets = [
        _market("mkt-a", ["yes", "no"]),
        _market("mkt-b", ["yes", "maybe"]),
    ]
    outcome_ids = collector_runtime.collect_outcome_ids(markets, max_outcomes_per_venue=3)

    assert outcome_ids == ["kalshi:mkt-a:yes", "kalshi:mkt-a:no", "kalshi:mkt-b:yes"]


def test_collect_outcome_ids_rejects_non_positive_cap() -> None:
    markets = [_market("mkt-a", ["yes", "no"])]

    with pytest.raises(ValueError, match="max_outcomes_per_venue"):
        collector_runtime.collect_outcome_ids(markets, max_outcomes_per_venue=0)


def test_build_pipeline_contexts_creates_connectors_for_enabled_venues() -> None:
    settings = _settings()
    messages: list[tuple[str, bool]] = []

    def _factory(
        exchange_name: str,
        config: config_models.VenueConfig,
    ) -> _StubAdapter:
        assert exchange_name == config.name
        return _StubAdapter(config.name)

    contexts = asyncio.run(
        collector_runtime.build_pipeline_contexts(
            settings,
            max_outcomes_per_venue=10,
            adapter_factory=_factory,
            emit=lambda message, is_error: _emit(messages, message, is_error),
        )
    )

    connector_ids = sorted(context.pipeline.connector.connector_id for context in contexts)
    assert len(contexts) == 4
    assert connector_ids == [
        "kalshi:BookSnapshotPoller",
        "kalshi:MarketRefreshPoller",
        "kalshi:OHLCVPoller",
        "kalshi:TradePoller",
    ]
    assert messages == []


def test_build_polling_scheduler_counts_success_and_reports_failures() -> None:
    messages: list[tuple[str, bool]] = []
    success = collector_runtime.PipelineContext(
        pipeline=cast(
            collector_pipeline.PollingPipeline,
            _FakePipeline("kalshi:good", 30.0, "completed"),
        ),
        rate_limiter=connector_rate_limiter.TokenBucketRateLimiter(rpm=600),
    )
    failing = collector_runtime.PipelineContext(
        pipeline=cast(
            collector_pipeline.PollingPipeline,
            _FakePipeline("kalshi:bad", 30.0, "failed"),
        ),
        rate_limiter=connector_rate_limiter.TokenBucketRateLimiter(rpm=600),
    )

    scheduler = collector_runtime.build_polling_scheduler(
        [success, failing],
        emit=lambda message, is_error: _emit(messages, message, is_error),
    )
    completed = asyncio.run(scheduler.run_once())

    assert set(completed) == {"kalshi:good"}
    assert len(messages) == 1
    assert messages[0][1] is True
    assert "Pipeline failed (kalshi:bad)" in messages[0][0]


def test_run_polling_pipelines_once_raises_when_no_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()

    async def _empty_contexts(
        *_args: object,
        **_kwargs: object,
    ) -> list[collector_runtime.PipelineContext]:
        return []

    monkeypatch.setattr(collector_runtime, "build_pipeline_contexts", _empty_contexts)

    def _adapter_factory(
        exchange_name: str,
        config: config_models.VenueConfig,
    ) -> adapters_base.VenueAdapter:
        del config
        return _StubAdapter(exchange_name)

    with pytest.raises(ValueError, match="No polling pipelines were created"):
        asyncio.run(
            collector_runtime.run_polling_pipelines(
                settings,
                once=True,
                max_outcomes_per_venue=10,
                adapter_factory=_adapter_factory,
                emit=lambda _message, _is_error: None,
            )
        )


def test_run_polling_pipelines_rejects_non_positive_max_outcomes() -> None:
    settings = _settings()

    def _adapter_factory(
        exchange_name: str,
        config: config_models.VenueConfig,
    ) -> adapters_base.VenueAdapter:
        del config
        return _StubAdapter(exchange_name)

    with pytest.raises(ValueError, match="max_outcomes_per_venue"):
        asyncio.run(
            collector_runtime.run_polling_pipelines(
                settings,
                once=True,
                max_outcomes_per_venue=0,
                adapter_factory=_adapter_factory,
                emit=lambda _message, _is_error: None,
            )
        )


def test_run_streaming_pipelines_once_raises_when_no_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()

    async def _empty_stream_contexts(
        *_args: object,
        **_kwargs: object,
    ) -> list[collector_runtime.StreamingPipelineContext]:
        return []

    monkeypatch.setattr(
        collector_runtime,
        "build_streaming_pipeline_contexts",
        _empty_stream_contexts,
    )

    def _adapter_factory(
        exchange_name: str,
        config: config_models.VenueConfig,
    ) -> adapters_base.VenueAdapter:
        del config
        return _StubAdapter(exchange_name)

    with pytest.raises(ValueError, match="No streaming pipelines were created"):
        asyncio.run(
            collector_runtime.run_streaming_pipelines(
                settings,
                once=True,
                max_outcomes_per_venue=10,
                adapter_factory=_adapter_factory,
                emit=lambda _message, _is_error: None,
            )
        )


def test_run_polling_and_streaming_once_sums_run_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()

    async def _fake_run_polling(*_args: object, **_kwargs: object) -> int:
        return 3

    async def _fake_run_streaming(*_args: object, **_kwargs: object) -> int:
        return 2

    monkeypatch.setattr(collector_runtime, "run_polling_pipelines", _fake_run_polling)
    monkeypatch.setattr(collector_runtime, "run_streaming_pipelines", _fake_run_streaming)

    total = asyncio.run(
        collector_runtime.run_polling_and_streaming(
            settings,
            once=True,
            max_outcomes_per_venue=10,
            adapter_factory=lambda _exchange, _cfg: _StubAdapter("kalshi"),
            emit=lambda _message, _is_error: None,
        )
    )
    assert total == 5
