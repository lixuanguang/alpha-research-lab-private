"""Unit tests for storage conventions, writer, and reader behavior."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pytest

import alpha_core.events.models as event_models
import alpha_core.storage.conventions as storage_conventions
import alpha_core.storage.duckdb_layer as duckdb_layer
import alpha_core.storage.parquet_reader as parquet_reader
import alpha_core.storage.parquet_writer as parquet_writer
import alpha_core.utils.ids as ids_utils


def _make_trade(*, trade_index: int, venue: str, ts_event: datetime) -> event_models.CanonicalTrade:
    payload: dict[str, object] = {
        "instrument_id": f"{venue}:market-1:yes",
        "venue_id": venue,
        "event_type": event_models.EventType.TRADE,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(seconds=1),
        "schema_version": 1,
        "price": Decimal("0.50") + Decimal(trade_index % 10) / Decimal("100"),
        "size": Decimal("1") + Decimal(trade_index % 3),
        "side": event_models.TradeSide.BUY if trade_index % 2 == 0 else event_models.TradeSide.SELL,
        "trade_id": f"trade-{trade_index}",
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalTrade.model_validate(payload)


def _make_book(
    *,
    book_index: int,
    venue: str,
    ts_event: datetime,
) -> event_models.CanonicalBookSnapshot:
    payload: dict[str, object] = {
        "instrument_id": f"{venue}:market-1:yes",
        "venue_id": venue,
        "event_type": event_models.EventType.BOOK_SNAPSHOT,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(seconds=1),
        "schema_version": 1,
        "bids": [{"price": "0.49", "size": str(10 + book_index)}],
        "asks": [{"price": "0.51", "size": str(12 + book_index)}],
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalBookSnapshot.model_validate(payload)


def _make_ohlcv(
    *,
    candle_index: int,
    venue: str,
    ts_event: datetime,
    resolution: str,
) -> event_models.CanonicalOHLCV:
    payload: dict[str, object] = {
        "instrument_id": f"{venue}:market-1:yes",
        "venue_id": venue,
        "event_type": event_models.EventType.OHLCV,
        "ts_event": ts_event,
        "ts_record": ts_event + timedelta(seconds=1),
        "schema_version": 1,
        "open": Decimal("0.50"),
        "high": Decimal("0.55"),
        "low": Decimal("0.48"),
        "close": Decimal("0.52") + Decimal(candle_index) / Decimal("1000"),
        "volume": Decimal("100") + Decimal(candle_index),
        "resolution": resolution,
    }
    payload["event_id"] = ids_utils.generate_event_id(payload)
    return event_models.CanonicalOHLCV.model_validate(payload)


def _parquet_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.parquet"))


class _FakeDuckDBResult:
    def __init__(self, table: pa.Table) -> None:
        self._table = table

    def fetch_arrow_table(self) -> pa.Table:
        return self._table


class _FakeDuckDBConnection:
    def __init__(self, table: pa.Table) -> None:
        self._table = table
        self.calls: list[tuple[str, tuple[object, ...] | None]] = []

    def execute(
        self,
        sql: str,
        parameters: tuple[object, ...] | None = None,
    ) -> _FakeDuckDBResult:
        self.calls.append((sql, parameters))
        return _FakeDuckDBResult(self._table)


class _FakeDuckDBModule:
    def __init__(self, table: pa.Table) -> None:
        self.connection = _FakeDuckDBConnection(table)

    def connect(self) -> _FakeDuckDBConnection:
        return self.connection


def test_write_trades_creates_partitioned_parquet_files(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    base_ts = datetime(2026, 2, 28, 12, 0, tzinfo=UTC)

    trades = [
        _make_trade(trade_index=index, venue="kalshi", ts_event=base_ts + timedelta(seconds=index))
        for index in range(50)
    ]
    trades.extend(
        _make_trade(
            trade_index=50 + index,
            venue="polymarket",
            ts_event=base_ts + timedelta(days=1, seconds=index),
        )
        for index in range(50)
    )

    dataset_root = writer.write_trades(trades)

    parquet_files = _parquet_files(dataset_root)
    assert parquet_files
    assert (dataset_root / "venue=kalshi" / "date=2026-02-28").exists()
    assert (dataset_root / "venue=polymarket" / "date=2026-03-01").exists()


def test_read_trades_filters_by_venue_and_date_window(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    reader = parquet_reader.ParquetEventReader(tmp_path)

    day_one = datetime(2026, 2, 28, 10, 0, tzinfo=UTC)
    day_two = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)

    trades = [
        _make_trade(trade_index=index, venue="kalshi", ts_event=day_one + timedelta(minutes=index))
        for index in range(10)
    ]
    trades.extend(
        _make_trade(
            trade_index=100 + index,
            venue="kalshi",
            ts_event=day_two + timedelta(minutes=index),
        )
        for index in range(10)
    )
    trades.extend(
        _make_trade(
            trade_index=200 + index,
            venue="polymarket",
            ts_event=day_two + timedelta(minutes=index),
        )
        for index in range(5)
    )

    writer.write_trades(trades)

    filtered = reader.read_trades(
        venue="kalshi",
        start=datetime(2026, 3, 1, 0, 0, tzinfo=UTC),
        end=datetime(2026, 3, 1, 23, 59, 59, tzinfo=UTC),
    )

    trade_ids = set(filtered.column("trade_id").to_pylist())
    assert trade_ids == {f"trade-{100 + index}" for index in range(10)}


def test_trade_schema_matches_expected_columns_and_types(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    reader = parquet_reader.ParquetEventReader(tmp_path)

    trade = _make_trade(
        trade_index=1,
        venue="kalshi",
        ts_event=datetime(2026, 2, 28, 12, 0, tzinfo=UTC),
    )
    writer.write_trades([trade])

    table = reader.read_trades(
        venue=None,
        start=None,
        end=None,
    )

    assert table.schema == storage_conventions.TRADE_PARQUET_SCHEMA
    assert table.schema.field("price").type == pa.decimal128(20, 10)
    assert table.schema.field("ts_event").type == pa.timestamp("us", tz="UTC")


def test_read_trades_returns_empty_table_when_dataset_missing(tmp_path: Path) -> None:
    reader = parquet_reader.ParquetEventReader(tmp_path)

    table = reader.read_trades(venue="kalshi", start=None, end=None)

    assert table.num_rows == 0
    assert table.schema == storage_conventions.TRADE_PARQUET_SCHEMA


def test_write_books_creates_partitioned_paths_with_hour(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    base_ts = datetime(2026, 2, 28, 9, 0, tzinfo=UTC)

    books = [
        _make_book(book_index=0, venue="kalshi", ts_event=base_ts),
        _make_book(book_index=1, venue="kalshi", ts_event=base_ts + timedelta(hours=1)),
    ]

    dataset_root = writer.write_books(books)

    parquet_files = _parquet_files(dataset_root)
    assert parquet_files
    assert (dataset_root / "venue=kalshi" / "date=2026-02-28" / "hour=09").exists()
    assert (dataset_root / "venue=kalshi" / "date=2026-02-28" / "hour=10").exists()


def test_read_books_filters_by_venue_and_time_window(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    reader = parquet_reader.ParquetEventReader(tmp_path)
    base_ts = datetime(2026, 2, 28, 9, 0, tzinfo=UTC)

    writer.write_books(
        [
            _make_book(book_index=0, venue="kalshi", ts_event=base_ts),
            _make_book(book_index=1, venue="kalshi", ts_event=base_ts + timedelta(hours=1)),
            _make_book(book_index=2, venue="polymarket", ts_event=base_ts + timedelta(hours=1)),
        ]
    )

    filtered = reader.read_books(
        venue="kalshi",
        start=base_ts,
        end=base_ts + timedelta(minutes=30),
    )

    assert filtered.num_rows == 1
    assert set(filtered.column("venue").to_pylist()) == {"kalshi"}


def test_read_books_returns_empty_table_when_dataset_missing(tmp_path: Path) -> None:
    reader = parquet_reader.ParquetEventReader(tmp_path)

    table = reader.read_books()

    assert table.num_rows == 0
    assert table.schema == storage_conventions.BOOK_PARQUET_SCHEMA


def test_write_ohlcv_creates_partitioned_paths_with_resolution(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    base_ts = datetime(2026, 2, 28, 9, 0, tzinfo=UTC)

    candles = [
        _make_ohlcv(
            candle_index=0,
            venue="polymarket",
            ts_event=base_ts,
            resolution="1h",
        ),
        _make_ohlcv(
            candle_index=1,
            venue="polymarket",
            ts_event=base_ts + timedelta(days=1),
            resolution="1h",
        ),
        _make_ohlcv(
            candle_index=2,
            venue="polymarket",
            ts_event=base_ts,
            resolution="5m",
        ),
    ]

    dataset_root = writer.write_ohlcv(candles)

    parquet_files = _parquet_files(dataset_root)
    assert parquet_files
    assert (dataset_root / "venue=polymarket" / "resolution=1h" / "date=2026-02-28").exists()
    assert (dataset_root / "venue=polymarket" / "resolution=1h" / "date=2026-03-01").exists()
    assert (dataset_root / "venue=polymarket" / "resolution=5m" / "date=2026-02-28").exists()


def test_read_ohlcv_filters_by_venue_resolution_and_time_window(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    reader = parquet_reader.ParquetEventReader(tmp_path)
    base_ts = datetime(2026, 2, 28, 9, 0, tzinfo=UTC)

    writer.write_ohlcv(
        [
            _make_ohlcv(candle_index=0, venue="kalshi", ts_event=base_ts, resolution="1h"),
            _make_ohlcv(candle_index=1, venue="kalshi", ts_event=base_ts, resolution="5m"),
            _make_ohlcv(
                candle_index=2,
                venue="polymarket",
                ts_event=base_ts + timedelta(days=1),
                resolution="1h",
            ),
        ]
    )

    filtered = reader.read_ohlcv(
        venue="kalshi",
        resolution="1h",
        start=base_ts - timedelta(minutes=1),
        end=base_ts + timedelta(minutes=1),
    )

    assert filtered.num_rows == 1
    assert filtered.column("resolution").to_pylist() == ["1h"]
    assert set(filtered.column("venue").to_pylist()) == {"kalshi"}


def test_read_ohlcv_returns_empty_table_when_dataset_missing(tmp_path: Path) -> None:
    reader = parquet_reader.ParquetEventReader(tmp_path)

    table = reader.read_ohlcv()

    assert table.num_rows == 0
    assert table.schema == storage_conventions.OHLCV_PARQUET_SCHEMA


def test_read_methods_support_default_optional_arguments(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    reader = parquet_reader.ParquetEventReader(tmp_path)
    ts = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

    writer.write_books([_make_book(book_index=1, venue="kalshi", ts_event=ts)])
    writer.write_ohlcv([_make_ohlcv(candle_index=1, venue="kalshi", ts_event=ts, resolution="1h")])

    books = reader.read_books()
    candles = reader.read_ohlcv()

    assert books.num_rows == 1
    assert candles.num_rows == 1


def test_write_trades_with_empty_input_creates_dataset_root_without_files(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)

    dataset_root = writer.write_trades([])

    assert dataset_root == (
        tmp_path
        / storage_conventions.StorageTier.SILVER.value
        / storage_conventions.TRADE_DATASET_NAME
    )
    assert dataset_root.exists()
    assert _parquet_files(dataset_root) == []


def test_write_books_with_empty_input_creates_dataset_root_without_files(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)

    dataset_root = writer.write_books([])

    assert dataset_root == (
        tmp_path
        / storage_conventions.StorageTier.SILVER.value
        / storage_conventions.BOOK_DATASET_NAME
    )
    assert dataset_root.exists()
    assert _parquet_files(dataset_root) == []


def test_write_ohlcv_with_empty_input_creates_dataset_root_without_files(tmp_path: Path) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)

    dataset_root = writer.write_ohlcv([])

    assert dataset_root == (
        tmp_path
        / storage_conventions.StorageTier.SILVER.value
        / storage_conventions.OHLCV_DATASET_NAME
    )
    assert dataset_root.exists()
    assert _parquet_files(dataset_root) == []


def test_storage_conventions_dataset_root_and_partition_columns_are_consistent() -> None:
    root = Path("/tmp/storage-root")

    assert storage_conventions.dataset_root(
        root,
        storage_conventions.StorageTier.SILVER,
        storage_conventions.TRADE_DATASET_NAME,
    ) == Path("/tmp/storage-root/silver/trades")
    assert storage_conventions.resolve_partition_columns("silver_trades") == ["venue", "date"]
    assert storage_conventions.resolve_partition_columns("silver_books") == [
        "venue",
        "date",
        "hour",
    ]
    assert storage_conventions.resolve_partition_columns("silver_ohlcv") == [
        "venue",
        "resolution",
        "date",
    ]


def test_resolve_partition_columns_raises_for_unknown_dataset_key() -> None:
    with pytest.raises(KeyError, match="Unknown storage dataset key"):
        storage_conventions.resolve_partition_columns("unknown_dataset")


def test_duckdb_source_validation_allows_registered_view_and_cte() -> None:
    statement = (
        "WITH recent AS (SELECT * FROM silver_trades) "
        "SELECT * FROM recent JOIN silver_trades ON recent.trade_id = silver_trades.trade_id"
    )
    duckdb_layer._validate_allowed_query_sources(statement, {"silver_trades"})


def test_duckdb_source_validation_rejects_unregistered_relation() -> None:
    with pytest.raises(ValueError, match="Unknown relation"):
        duckdb_layer._validate_allowed_query_sources(
            "SELECT * FROM ad_hoc_table",
            {"silver_trades"},
        )


def test_duckdb_source_validation_rejects_quoted_unregistered_relation() -> None:
    with pytest.raises(ValueError, match="Unknown relation"):
        duckdb_layer._validate_allowed_query_sources(
            'SELECT * FROM "sqlite_master"',
            {"silver_trades"},
        )


def test_duckdb_source_validation_allows_quoted_registered_relation() -> None:
    duckdb_layer._validate_allowed_query_sources(
        'SELECT * FROM "silver_trades"',
        {"silver_trades"},
    )


def test_duckdb_source_validation_rejects_table_function() -> None:
    with pytest.raises(ValueError, match="Table functions are not allowed"):
        duckdb_layer._validate_allowed_query_sources(
            "SELECT * FROM read_parquet('/tmp/any.parquet')",
            {"silver_trades"},
        )


def test_duckdb_query_rejects_dml_inside_with_statement(tmp_path: Path) -> None:
    if duckdb_layer.duckdb_module is None:
        pytest.skip("duckdb is not installed")

    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    with pytest.raises(ValueError, match="Disallowed SQL keyword"):
        analytics.query(
            "WITH staged AS (SELECT 1) INSERT INTO forbidden_table SELECT * FROM staged"
        )


def test_duckdb_query_allows_keywords_inside_string_literals(tmp_path: Path) -> None:
    if duckdb_layer.duckdb_module is None:
        pytest.skip("duckdb is not installed")

    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    table = analytics.query("SELECT 'drop table maybe' AS text_value")

    assert table.num_rows == 1
    assert table.column("text_value").to_pylist() == ["drop table maybe"]


def test_duckdb_analytics_init_requires_duckdb_module(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(duckdb_layer, "duckdb_module", None)
    with pytest.raises(ModuleNotFoundError, match="duckdb is required"):
        duckdb_layer.DuckDBAnalytics(tmp_path)


def test_duckdb_query_executes_with_and_without_parameters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_duckdb = _FakeDuckDBModule(pa.table({"value": [7]}))
    monkeypatch.setattr(duckdb_layer, "duckdb_module", fake_duckdb)
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)
    analytics._registered_views.add("silver_trades")

    table_no_params = analytics.query("-- leading comment\nSELECT 1 AS value FROM silver_trades")
    table_with_params = analytics.query(
        "SELECT ? AS value FROM silver_trades",
        parameters=(7,),
    )

    assert table_no_params.column("value").to_pylist() == [7]
    assert table_with_params.column("value").to_pylist() == [7]
    assert fake_duckdb.connection.calls[0][1] is None
    assert fake_duckdb.connection.calls[1][1] == (7,)


def test_duckdb_query_rejects_empty_and_multi_statement_sql(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_duckdb = _FakeDuckDBModule(pa.table({"value": [1]}))
    monkeypatch.setattr(duckdb_layer, "duckdb_module", fake_duckdb)
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    with pytest.raises(ValueError, match="must be non-empty"):
        analytics.query("   ")

    with pytest.raises(ValueError, match="single SQL statement"):
        analytics.query("SELECT 1; SELECT 2")


def test_duckdb_register_silver_rejects_unsupported_event_type(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_duckdb = _FakeDuckDBModule(pa.table({"value": [1]}))
    monkeypatch.setattr(duckdb_layer, "duckdb_module", fake_duckdb)
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    with pytest.raises(ValueError, match="Unsupported event_type"):
        analytics.register_silver("invalid")


def test_duckdb_register_silver_uses_empty_view_when_dataset_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_duckdb = _FakeDuckDBModule(pa.table({"value": [1]}))
    monkeypatch.setattr(duckdb_layer, "duckdb_module", fake_duckdb)
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    analytics.register_silver("trades")

    assert "silver_trades" in analytics._registered_views
    sql, _ = fake_duckdb.connection.calls[-1]
    assert "CREATE OR REPLACE VIEW" in sql
    assert "WHERE FALSE" in sql


def test_duckdb_register_silver_reads_parquet_when_dataset_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    writer = parquet_writer.ParquetEventWriter(tmp_path)
    writer.write_trades(
        [
            _make_trade(
                trade_index=1,
                venue="kalshi",
                ts_event=datetime(2026, 3, 1, 10, 0, tzinfo=UTC),
            )
        ]
    )
    fake_duckdb = _FakeDuckDBModule(pa.table({"value": [1]}))
    monkeypatch.setattr(duckdb_layer, "duckdb_module", fake_duckdb)
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    analytics.register_silver("trades")

    assert "silver_trades" in analytics._registered_views
    sql, _ = fake_duckdb.connection.calls[-1]
    assert "read_parquet(" in sql
    assert "hive_partitioning=1" in sql
    assert "union_by_name=1" in sql


def test_duckdb_query_rejects_table_function_through_public_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_duckdb = _FakeDuckDBModule(pa.table({"value": [1]}))
    monkeypatch.setattr(duckdb_layer, "duckdb_module", fake_duckdb)
    analytics = duckdb_layer.DuckDBAnalytics(tmp_path)

    with pytest.raises(ValueError, match="Table functions are not allowed"):
        analytics.query("SELECT * FROM read_parquet('/tmp/path.parquet')")


def test_duckdb_internal_helpers_cover_edge_cases() -> None:
    assert duckdb_layer._quote_identifier('a"b') == '"a""b"'
    assert duckdb_layer._is_read_only_statement(" EXPLAIN SELECT 1")
    assert not duckdb_layer._is_read_only_statement("PRAGMA table_info('x')")

    stripped = duckdb_layer._strip_comments("/* block */ SELECT 1 -- inline")
    assert "block" not in stripped
    assert "--" not in stripped

    with pytest.raises(ValueError, match="Disallowed SQL keyword"):
        duckdb_layer._raise_if_forbidden_sql("SELECT * FROM source INSERT INTO sink")

    assert duckdb_layer._arrow_type_to_duckdb_type(pa.string()) == "VARCHAR"
    assert duckdb_layer._arrow_type_to_duckdb_type(pa.int32()) == "INTEGER"
    assert duckdb_layer._arrow_type_to_duckdb_type(pa.decimal128(10, 2)) == "DECIMAL(10,2)"
    assert duckdb_layer._arrow_type_to_duckdb_type(pa.timestamp("us", tz="UTC")) == "TIMESTAMPTZ"
    with pytest.raises(TypeError, match="Unsupported Arrow type"):
        duckdb_layer._arrow_type_to_duckdb_type(pa.bool_())

    assert duckdb_layer._last_identifier_component('"schema"."ta""ble"') == '"ta""ble"'
    assert duckdb_layer._last_identifier_component("db.schema.table") == "table"
    assert duckdb_layer._last_identifier_component("   ") == ""
