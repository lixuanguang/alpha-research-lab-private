"""Integration test: silver → gold build → load → no look-ahead."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import alpha_core.instruments.master as master_mod
import alpha_core.instruments.models as instrument_models
import alpha_core.quality.gap_detector as gap_mod
import alpha_core.quality.partition_validator as pv_mod
import alpha_core.research.dataset as dataset_mod
import alpha_core.research.dataset_builder as builder_mod
import alpha_core.research.universe as universe_mod
import alpha_core.storage.parquet_reader as reader_mod

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BASE = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
_END = _BASE + timedelta(days=7)


def _make_market(venue: str, market_id: str, outcomes: list[str]) -> instrument_models.MarketSpec:
    return instrument_models.MarketSpec(
        market_id=market_id,
        venue=venue,
        title=f"{venue}/{market_id}",
        outcomes=[
            instrument_models.OutcomeSpec(
                outcome_id=oid,
                label=oid.upper(),
                canonical_id=f"{venue}:{market_id}:{oid}",
            )
            for oid in outcomes
        ],
        first_seen=_BASE - timedelta(days=1),
        last_updated=_BASE,
    )


def _build_silver_trades(n_events: int) -> pa.Table:
    """Synthetic silver trades representing normal + future-recorded rows."""
    step = timedelta(minutes=30)
    ts_events = [_BASE + step * i for i in range(n_events)]
    # Inject 3 "late-arriving" rows: ts_record is 10 days after ts_event (post-END)
    ts_records = list(ts_events)
    for i in [5, 10, 15]:
        if i < n_events:
            ts_records[i] = _END + timedelta(days=2)  # recorded AFTER our cutoff

    schema = pa.schema(
        [
            pa.field("event_id", pa.string()),
            pa.field("instrument_id", pa.string()),
            pa.field("venue_id", pa.string()),
            pa.field("event_type", pa.string()),
            pa.field("ts_event", pa.timestamp("us", tz="UTC")),
            pa.field("ts_record", pa.timestamp("us", tz="UTC")),
            pa.field("price", pa.float64()),
            pa.field("size", pa.float64()),
        ]
    )
    instruments = [f"p:m1:{'yes' if i % 2 == 0 else 'no'}" for i in range(n_events)]
    return pa.table(
        {
            "event_id": [f"e{i}" for i in range(n_events)],
            "instrument_id": instruments,
            "venue_id": ["p"] * n_events,
            "event_type": ["trade"] * n_events,
            "ts_event": ts_events,
            "ts_record": ts_records,
            "price": [0.5 + (i % 10) / 100.0 for i in range(n_events)],
            "size": [100.0] * n_events,
        },
        schema=schema,
    )


@pytest.fixture()
def setup(tmp_path: Path):  # type: ignore[no-untyped-def]  # pytest fixture
    """Return a fully wired (builder, config) pair with synthetic silver data."""
    master = master_mod.MarketMaster()
    master.register_market(_make_market("p", "m1", ["yes", "no"]))

    silver_trades = _build_silver_trades(n_events=50)

    mock_reader = MagicMock(spec=reader_mod.ParquetEventReader)
    mock_reader.read_trades.return_value = silver_trades
    mock_reader.read_ohlcv.return_value = pa.table({})
    mock_reader.read_books.return_value = pa.table({})

    mock_validator = MagicMock(spec=pv_mod.PartitionValidator)
    mock_gap = MagicMock(spec=gap_mod.GapDetector)
    mock_gap.detect_trade_gaps.return_value = []

    mgr = universe_mod.UniverseManager(master)
    builder = builder_mod.DatasetBuilder(
        reader=mock_reader,
        universe_mgr=mgr,
        quality_validator=mock_validator,
        gap_detector=mock_gap,
        storage_root=tmp_path,
    )
    config = dataset_mod.DatasetConfig(
        name="silver_to_gold",
        start=_BASE,
        end=_END,
        require_quality_pass=False,
    )
    return builder, config, tmp_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_build_and_load_roundtrip(setup) -> None:  # type: ignore[no-untyped-def]
    builder, config, _tmp_path = setup
    manifest = builder.build(config)

    # Reload via builder
    gold_ds = builder.load(manifest.dataset_id)
    assert gold_ds.manifest.dataset_id == manifest.dataset_id
    assert gold_ds.manifest.config.name == "silver_to_gold"


def test_no_look_ahead_via_ts_record(setup) -> None:  # type: ignore[no-untyped-def]
    """Gold trades must contain zero rows where ts_record > config.end."""
    builder, config, tmp_path = setup
    builder.build(config)

    gold_path = tmp_path / "gold" / "datasets" / "silver_to_gold" / "trades.parquet"
    assert gold_path.exists()
    result = pq.read_table(gold_path)

    leaked = [
        ts
        for ts in result.column("ts_record").to_pylist()
        if ts is not None and ts.replace(tzinfo=UTC) > _END
    ]
    assert len(leaked) == 0, (
        f"Look-ahead bias: {len(leaked)} row(s) with ts_record > end: {leaked[:3]}"
    )


def test_universe_roundtrip_in_gold_dataset(setup) -> None:  # type: ignore[no-untyped-def]
    """universe.parquet must exist and contain sensible instrument IDs."""
    builder, config, _tmp_path = setup
    manifest = builder.build(config)
    gold_ds = builder.load(manifest.dataset_id)

    instruments = gold_ds.instruments()
    assert len(instruments) > 0
    for instr_id in instruments:
        assert ":" in instr_id, f"Malformed instrument_id: {instr_id}"


def test_list_datasets_finds_built_dataset(setup) -> None:  # type: ignore[no-untyped-def]
    builder, config, _tmp_path = setup
    manifest = builder.build(config)
    manifests = builder.list_datasets()
    ids = {m.dataset_id for m in manifests}
    assert manifest.dataset_id in ids


def test_manifest_json_roundtrip(setup) -> None:  # type: ignore[no-untyped-def]
    """_meta.json must round-trip through DatasetManifest without data loss."""
    builder, config, tmp_path = setup
    manifest = builder.build(config)

    meta_path = tmp_path / "gold" / "datasets" / "silver_to_gold" / "_meta.json"
    reloaded = dataset_mod.DatasetManifest.model_validate_json(meta_path.read_text())

    assert reloaded.dataset_id == manifest.dataset_id
    assert reloaded.config.name == manifest.config.name
    assert reloaded.schema_version == 1
