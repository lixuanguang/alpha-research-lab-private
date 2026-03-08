"""Integration tests for LA-020: cursor persistence and replay-package manifest flow.

Covers:
- BackfillManager emits a replay package + cursor on success
- Cursor watermark is the window end; replay_package_id is populated in result
- Replay package survives a JSON round-trip via ReplayPackageStore
- Resume flow: get_latest_cursor() returns window.end after successful backfill
- Partial-failure (failed run) is excluded from cursor lookup
- Lineage + replay manifests remain consistent after failure → resume sequence
"""

from __future__ import annotations

import asyncio
import gzip
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import apps.data_collector.backfill as collector_backfill
import pyarrow.parquet as pq

import alpha_core.adapters.base as adapters_base
import alpha_core.events.models as event_models
import alpha_core.events.quality as event_quality
import alpha_core.instruments.models as instrument_models
import alpha_core.storage.bronze_writer as storage_bronze
import alpha_core.storage.lineage as storage_lineage
import alpha_core.storage.parquet_writer as storage_parquet
import alpha_core.storage.replay_package as storage_replay
import alpha_core.utils.ids as ids_utils

# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
_WINDOW_START = _NOW - timedelta(days=2)
_WINDOW_END = _NOW - timedelta(days=1)


def _trade(
    trade_id: str,
    ts: datetime,
    outcome_id: str = "polymarket:mkt-a:yes",
) -> event_models.CanonicalTrade:
    payload: dict[str, object] = {
        "instrument_id": outcome_id,
        "venue_id": "polymarket",
        "event_type": event_models.EventType.TRADE,
        "ts_event": ts,
        "ts_record": ts + timedelta(milliseconds=10),
        "schema_version": 1,
        "price": Decimal("0.60"),
        "size": Decimal("5"),
        "side": event_models.TradeSide.BUY,
        "trade_id": trade_id,
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalTrade.model_validate(payload)


class _StubAdapter(adapters_base.VenueAdapter):
    """Minimal adapter that returns a fixed list of trades."""

    def __init__(
        self, trades: list[event_models.CanonicalTrade], *, should_fail: bool = False
    ) -> None:
        self._trades = trades
        self._should_fail = should_fail

    def venue_name(self) -> str:
        return "polymarket"

    async def fetch_markets(self) -> list[instrument_models.MarketSpec]:
        return []

    async def fetch_markets_with_raw(
        self,
    ) -> tuple[list[instrument_models.MarketSpec], list[object]]:
        return [], []

    async def fetch_trades(
        self,
        outcome_id: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[event_models.CanonicalTrade]:
        if self._should_fail:
            raise RuntimeError("Simulated adapter failure")
        return list(self._trades)

    async def fetch_trades_with_raw(
        self,
        outcome_id: str,
        since: datetime | None = None,
        limit: int = 100,
    ) -> tuple[list[event_models.CanonicalTrade], list[object]]:
        trades = await self.fetch_trades(outcome_id, since=since, limit=limit)
        return trades, [t.model_dump(mode="json") for t in trades]

    async def fetch_ohlcv(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> list[event_models.CanonicalOHLCV]:
        return []

    async def fetch_ohlcv_with_raw(
        self,
        outcome_id: str,
        resolution: str = "1h",
        limit: int = 100,
    ) -> tuple[list[event_models.CanonicalOHLCV], list[object]]:
        return [], []

    async def fetch_order_book(self, outcome_id: str) -> event_models.CanonicalBookSnapshot:
        raise NotImplementedError

    async def fetch_order_book_with_raw(
        self, outcome_id: str
    ) -> tuple[event_models.CanonicalBookSnapshot, object]:
        raise NotImplementedError


def _make_manager(
    tmp_path: Path,
    adapter: _StubAdapter,
    *,
    with_replay_store: bool = True,
) -> collector_backfill.BackfillManager:
    replay_store = storage_replay.ReplayPackageStore(tmp_path) if with_replay_store else None
    return collector_backfill.BackfillManager(
        adapter=adapter,
        dependencies=collector_backfill.BackfillDependencies(
            bronze_writer=storage_bronze.BronzeWriter(tmp_path),
            silver_writer=storage_parquet.ParquetEventWriter(tmp_path),
            quality_checker=event_quality.EventQualityChecker(),
            lineage_store=storage_lineage.LineageStore(tmp_path),
            replay_package_store=replay_store,
            storage_root=tmp_path,
        ),
    )


def _silver_trade_ids(storage_root: Path) -> list[str]:
    dataset_root = storage_root / "silver" / "trades"
    if not dataset_root.exists() or not list(dataset_root.rglob("*.parquet")):
        return []
    return sorted(
        str(trade_id) for trade_id in pq.read_table(dataset_root).column("trade_id").to_pylist()
    )


def _bronze_trade_ids(storage_root: Path) -> list[str]:
    trade_ids: list[str] = []
    bronze_root = storage_root / "bronze" / "trades"
    if not bronze_root.exists():
        return trade_ids
    for path in sorted(bronze_root.rglob("run_*.jsonl.gz")):
        with gzip.open(path, mode="rt", encoding="utf-8") as handle:
            for line in handle:
                payload = json.loads(line)["payload"]
                trade_id = payload.get("trade_id")
                if isinstance(trade_id, str):
                    trade_ids.append(trade_id)
    return sorted(trade_ids)


# ---------------------------------------------------------------------------
# Basic replay-package emission
# ---------------------------------------------------------------------------


def test_backfill_emits_replay_package_on_success(tmp_path: Path) -> None:
    """BackfillManager should emit a replay package when replay_package_store is set."""
    trades = [_trade(f"t{i}", _WINDOW_START + timedelta(hours=i)) for i in range(5)]
    manager = _make_manager(tmp_path, _StubAdapter(trades))

    result = asyncio.run(
        manager.backfill_trades(
            ["polymarket:mkt-a:yes"],
            start=_WINDOW_START,
            end=_WINDOW_END,
        )
    )

    assert result.replay_package_id is not None
    assert result.replay_package_id != ""


def test_backfill_result_cursor_watermark_equals_window_end(tmp_path: Path) -> None:
    trades = [_trade("t1", _WINDOW_START + timedelta(hours=1))]
    manager = _make_manager(tmp_path, _StubAdapter(trades))

    result = asyncio.run(
        manager.backfill_trades(
            ["polymarket:mkt-a:yes"],
            start=_WINDOW_START,
            end=_WINDOW_END,
        )
    )

    assert result.cursor_watermark_utc == _WINDOW_END


def test_replay_package_is_loadable_from_store_after_backfill(tmp_path: Path) -> None:
    """The emitted package must be retrievable via ReplayPackageStore.get()."""
    trades = [_trade(f"t{i}", _WINDOW_START + timedelta(hours=i)) for i in range(3)]
    manager = _make_manager(tmp_path, _StubAdapter(trades))

    result = asyncio.run(
        manager.backfill_trades(
            ["polymarket:mkt-a:yes"],
            start=_WINDOW_START,
            end=_WINDOW_END,
        )
    )

    store = storage_replay.ReplayPackageStore(tmp_path)
    assert result.replay_package_id is not None
    loaded = store.get(result.replay_package_id)

    assert loaded is not None
    assert loaded.venue == "polymarket"
    assert loaded.source_run_ids == [result.run_id]
    assert loaded.window_start == _WINDOW_START
    assert loaded.window_end == _WINDOW_END
    assert loaded.event_types == ["trades"]
    assert loaded.cursor_watermark_utc == _WINDOW_END


def test_replay_package_manifest_integrity_hash_is_set(tmp_path: Path) -> None:
    trades = [_trade("t1", _WINDOW_START + timedelta(minutes=30))]
    manager = _make_manager(tmp_path, _StubAdapter(trades))

    result = asyncio.run(
        manager.backfill_trades(
            ["polymarket:mkt-a:yes"],
            start=_WINDOW_START,
            end=_WINDOW_END,
        )
    )

    store = storage_replay.ReplayPackageStore(tmp_path)
    assert result.replay_package_id is not None
    loaded = store.get(result.replay_package_id)
    assert loaded is not None
    assert len(loaded.integrity_hash) == 64  # SHA-256 hex


def test_no_replay_package_when_store_not_provided(tmp_path: Path) -> None:
    """replay_package_id should be None when replay_package_store is not wired up."""
    trades = [_trade("t1", _WINDOW_START + timedelta(hours=1))]
    manager = _make_manager(tmp_path, _StubAdapter(trades), with_replay_store=False)

    result = asyncio.run(
        manager.backfill_trades(
            ["polymarket:mkt-a:yes"],
            start=_WINDOW_START,
            end=_WINDOW_END,
        )
    )

    assert result.replay_package_id is None
    # cursor_watermark should still be set even without replay store
    assert result.cursor_watermark_utc == _WINDOW_END


# ---------------------------------------------------------------------------
# Lineage cursor persistence
# ---------------------------------------------------------------------------


def test_lineage_cursor_is_persisted_after_successful_backfill(tmp_path: Path) -> None:
    """LineageStore must record cursor_watermark_utc, resume_safe, and replay_package_id."""
    trades = [_trade("t1", _WINDOW_START + timedelta(hours=1))]
    manager = _make_manager(tmp_path, _StubAdapter(trades))

    result = asyncio.run(
        manager.backfill_trades(
            ["polymarket:mkt-a:yes"],
            start=_WINDOW_START,
            end=_WINDOW_END,
        )
    )

    lineage_store = storage_lineage.LineageStore(tmp_path)
    completed_run = lineage_store.get_run(result.run_id)

    assert completed_run is not None
    assert completed_run.status == "completed"
    assert completed_run.cursor_type == "ts_event"
    assert completed_run.cursor_watermark_utc == _WINDOW_END
    assert completed_run.resume_safe is True
    assert completed_run.replay_package_id == result.replay_package_id


def test_get_latest_cursor_returns_window_end_after_successful_backfill(tmp_path: Path) -> None:
    trades = [_trade("t1", _WINDOW_START + timedelta(hours=1))]
    manager = _make_manager(tmp_path, _StubAdapter(trades))

    asyncio.run(
        manager.backfill_trades(
            ["polymarket:mkt-a:yes"],
            start=_WINDOW_START,
            end=_WINDOW_END,
        )
    )

    lineage_store = storage_lineage.LineageStore(tmp_path)
    latest = lineage_store.get_latest_cursor("polymarket")

    assert latest is not None
    assert latest.cursor_watermark_utc == _WINDOW_END
    assert latest.resume_safe is True


# ---------------------------------------------------------------------------
# Resume flow
# ---------------------------------------------------------------------------


def test_resume_flow_cursor_advances_window_end_across_two_runs(tmp_path: Path) -> None:
    """Resume backfills must advance the cursor without replaying boundary data."""
    lineage_store = storage_lineage.LineageStore(tmp_path)
    boundary_trade = _trade("t1", _WINDOW_END)

    # --- Run 1: window [T0, T1] ---
    t1_end = _WINDOW_END
    manager = _make_manager(tmp_path, _StubAdapter([boundary_trade]))
    asyncio.run(
        manager.backfill_trades(
            ["polymarket:mkt-a:yes"],
            start=_WINDOW_START,
            end=t1_end,
        )
    )

    cursor_after_run1 = lineage_store.get_latest_cursor("polymarket")
    assert cursor_after_run1 is not None
    assert cursor_after_run1.cursor_watermark_utc == t1_end

    # --- Run 2: window [T1, T2] using cursor as resume point ---
    t2_end = t1_end + timedelta(days=1)
    manager2 = _make_manager(tmp_path, _StubAdapter([boundary_trade]))
    asyncio.run(
        manager2.backfill_trades(
            ["polymarket:mkt-a:yes"],
            start=t1_end,
            end=t2_end,
        )
    )

    cursor_after_run2 = lineage_store.get_latest_cursor("polymarket")
    assert cursor_after_run2 is not None
    assert cursor_after_run2.cursor_watermark_utc == t2_end
    assert cursor_after_run2.cursor_watermark_utc > cursor_after_run1.cursor_watermark_utc
    assert _silver_trade_ids(tmp_path) == ["t1"]
    assert _bronze_trade_ids(tmp_path) == ["t1"]


def test_failed_run_excluded_from_cursor_lookup(tmp_path: Path) -> None:
    """A failed lineage run must not be returned by get_latest_cursor;
    only completed runs with a cursor watermark are eligible."""
    lineage_store = storage_lineage.LineageStore(tmp_path)
    trades = [_trade("t1", _WINDOW_START + timedelta(hours=1))]

    # Successful run first
    good_manager = _make_manager(tmp_path, _StubAdapter(trades))
    good_result = asyncio.run(
        good_manager.backfill_trades(
            ["polymarket:mkt-a:yes"],
            start=_WINDOW_START,
            end=_WINDOW_END,
        )
    )
    good_watermark = good_result.cursor_watermark_utc

    # Manually create a failed run in lineage to simulate a subsequent failure.
    # (Per-outcome fetch errors are swallowed in BackfillManager, so we use
    # the lineage API directly to model a hard process failure.)
    failed_run = lineage_store.start_run(
        venue="polymarket",
        connector_type="polling",
        options=storage_lineage.StartRunOptions(event_types=["trades"]),
    )
    lineage_store.fail_run(failed_run.run_id, "process crashed mid-run")

    # Cursor should still reflect the successful run's watermark
    latest = lineage_store.get_latest_cursor("polymarket")
    assert latest is not None
    assert latest.cursor_watermark_utc == good_watermark
    assert latest.resume_safe is True
    # The failed run must not appear as latest cursor
    assert latest.run_id != failed_run.run_id


# ---------------------------------------------------------------------------
# Replay-package JSON persistence round-trip
# ---------------------------------------------------------------------------


def test_replay_package_json_round_trip_preserves_all_fields(tmp_path: Path) -> None:
    """Reload a saved replay-package manifest and verify field-level equality."""
    trades = [_trade("t1", _WINDOW_START + timedelta(hours=2))]
    manager = _make_manager(tmp_path, _StubAdapter(trades))

    result = asyncio.run(
        manager.backfill_trades(
            ["polymarket:mkt-a:yes"],
            start=_WINDOW_START,
            end=_WINDOW_END,
        )
    )

    store = storage_replay.ReplayPackageStore(tmp_path)
    assert result.replay_package_id is not None
    loaded = store.get(result.replay_package_id)
    assert loaded is not None

    # Re-serialize and reload to verify full JSON round-trip
    raw_json = loaded.model_dump_json(indent=2)
    reloaded = storage_replay.ReplayPackageManifest.model_validate_json(raw_json)

    assert reloaded.package_id == loaded.package_id
    assert reloaded.venue == loaded.venue
    assert reloaded.source_run_ids == loaded.source_run_ids
    assert reloaded.window_start == loaded.window_start
    assert reloaded.window_end == loaded.window_end
    assert reloaded.cursor_watermark_utc == loaded.cursor_watermark_utc
    assert reloaded.integrity_hash == loaded.integrity_hash
    assert reloaded.schema_version == 1


def test_list_packages_contains_emitted_manifest(tmp_path: Path) -> None:
    """ReplayPackageStore.list_packages() must include the manifest emitted by backfill."""
    trades = [_trade("t1", _WINDOW_START + timedelta(hours=1))]
    manager = _make_manager(tmp_path, _StubAdapter(trades))

    result = asyncio.run(
        manager.backfill_trades(
            ["polymarket:mkt-a:yes"],
            start=_WINDOW_START,
            end=_WINDOW_END,
        )
    )

    store = storage_replay.ReplayPackageStore(tmp_path)
    all_packages = store.list_packages(venue="polymarket")

    package_ids = [p.package_id for p in all_packages]
    assert result.replay_package_id in package_ids


def test_two_sequential_backfills_emit_two_distinct_packages(tmp_path: Path) -> None:
    """Each backfill window should produce a unique package with a distinct integrity hash."""
    trades = [_trade("t1", _WINDOW_START + timedelta(hours=1))]
    t1_end = _WINDOW_END
    t2_end = t1_end + timedelta(days=1)

    m1 = _make_manager(tmp_path, _StubAdapter(trades))
    r1 = asyncio.run(m1.backfill_trades(["polymarket:mkt-a:yes"], start=_WINDOW_START, end=t1_end))

    m2 = _make_manager(tmp_path, _StubAdapter(trades))
    r2 = asyncio.run(m2.backfill_trades(["polymarket:mkt-a:yes"], start=t1_end, end=t2_end))

    assert r1.replay_package_id != r2.replay_package_id

    store = storage_replay.ReplayPackageStore(tmp_path)
    assert r1.replay_package_id is not None
    assert r2.replay_package_id is not None
    pkg1 = store.get(r1.replay_package_id)
    pkg2 = store.get(r2.replay_package_id)
    assert pkg1 is not None and pkg2 is not None
    assert pkg1.integrity_hash != pkg2.integrity_hash


# ---------------------------------------------------------------------------
# Lineage run link to replay-package (traceability)
# ---------------------------------------------------------------------------


def test_lineage_run_links_to_replay_package_id(tmp_path: Path) -> None:
    """IngestionRun.replay_package_id must match the emitted manifest's package_id."""
    trades = [_trade("t1", _WINDOW_START + timedelta(hours=1))]
    manager = _make_manager(tmp_path, _StubAdapter(trades))

    result = asyncio.run(
        manager.backfill_trades(
            ["polymarket:mkt-a:yes"],
            start=_WINDOW_START,
            end=_WINDOW_END,
        )
    )

    lineage_store = storage_lineage.LineageStore(tmp_path)
    ingestion_run = lineage_store.get_run(result.run_id)
    assert ingestion_run is not None
    assert ingestion_run.replay_package_id == result.replay_package_id

    # Cross-check: manifest's source_run_ids contains this run_id
    store = storage_replay.ReplayPackageStore(tmp_path)
    assert result.replay_package_id is not None
    manifest = store.get(result.replay_package_id)
    assert manifest is not None
    assert result.run_id in manifest.source_run_ids
