"""Unit tests for bronze raw payload writer."""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

import pytest

import alpha_core.storage.bronze_writer as bronze_writer


def _read_gzip_lines(path: Path) -> list[str]:
    with gzip.open(path, mode="rt", encoding="utf-8") as handle:
        return [line.rstrip("\n") for line in handle.readlines()]


def test_write_raw_events_creates_partitioned_jsonl_gz(tmp_path: Path) -> None:
    writer = bronze_writer.BronzeWriter(tmp_path)
    events = [{"id": 1, "price": "0.51"}, {"id": 2, "price": "0.49"}]

    output = writer.write_raw_events(
        events,
        venue="Kalshi",
        event_type="Trades",
        run_id="abc123",
    )

    assert output.name == "run_abc123.jsonl.gz"
    assert output.parent.parent.name == "venue=kalshi"
    assert output.parent.parent.parent.name == "trades"

    lines = _read_gzip_lines(output)
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["run_id"] == "abc123"
    assert first["venue"] == "kalshi"
    assert first["event_type"] == "trades"
    assert first["payload"] == events[0]


def test_write_market_snapshot_creates_metadata_json_gz(tmp_path: Path) -> None:
    writer = bronze_writer.BronzeWriter(tmp_path)
    markets = [{"id": "m1"}, {"id": "m2"}]

    output = writer.write_market_snapshot(markets, venue="Polymarket", run_id="run-1")

    assert output.suffixes == [".json", ".gz"]
    assert output.parent.parent.name == "venue=polymarket"
    assert output.parent.parent.parent.name == "metadata"

    with gzip.open(output, mode="rt", encoding="utf-8") as handle:
        payload = json.loads(handle.read())

    assert payload["run_id"] == "run-1"
    assert payload["venue"] == "polymarket"
    assert payload["markets"] == markets


def test_write_raw_events_supports_empty_batch(tmp_path: Path) -> None:
    writer = bronze_writer.BronzeWriter(tmp_path)

    output = writer.write_raw_events([], venue="kalshi", event_type="trades", run_id="empty")

    assert output.exists()
    assert _read_gzip_lines(output) == []


def test_write_raw_events_appends_when_same_run_id_is_reused(tmp_path: Path) -> None:
    writer = bronze_writer.BronzeWriter(tmp_path)

    first_path = writer.write_raw_events(
        [{"id": 1}],
        venue="kalshi",
        event_type="trades",
        run_id="run-1",
    )
    second_path = writer.write_raw_events(
        [{"id": 2}],
        venue="kalshi",
        event_type="trades",
        run_id="run-1",
    )

    assert first_path == second_path
    lines = _read_gzip_lines(second_path)
    payload_ids = [json.loads(line)["payload"]["id"] for line in lines]
    assert payload_ids == [1, 2]


def test_bronze_writer_rejects_invalid_compression(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Only `gzip` compression"):
        bronze_writer.BronzeWriter(tmp_path, compression="zstd")


def test_bronze_writer_rejects_blank_partition_values(tmp_path: Path) -> None:
    writer = bronze_writer.BronzeWriter(tmp_path)

    with pytest.raises(ValueError, match="`venue` must be non-empty"):
        writer.write_raw_events([{"id": 1}], venue=" ", event_type="trades", run_id="x")


def test_bronze_writer_rejects_invalid_partition_tokens_and_run_ids(tmp_path: Path) -> None:
    writer = bronze_writer.BronzeWriter(tmp_path)

    with pytest.raises(ValueError, match="unsupported characters"):
        writer.write_raw_events([{"id": 1}], venue="kalshi/us", event_type="trades", run_id="ok")

    with pytest.raises(ValueError, match="unsupported characters"):
        writer.write_raw_events(
            [{"id": 1}],
            venue="kalshi",
            event_type="trades",
            run_id="../escape",
        )


@pytest.mark.perf
def test_bronze_writer_meets_d2_write_latency_and_compression_targets(tmp_path: Path) -> None:
    writer = bronze_writer.BronzeWriter(tmp_path)
    events = [
        {
            "event_index": index,
            "instrument_id": "kalshi:market-a:yes",
            "price": "0.5150",
            "size": "10",
            "side": "buy",
            "note": "market microstructure payload " * 8,
        }
        for index in range(1000)
    ]

    start = time.perf_counter()
    output = writer.write_raw_events(
        events,
        venue="kalshi",
        event_type="trades",
        run_id="perf-1k",
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    compressed_bytes = output.stat().st_size
    with gzip.open(output, mode="rb") as handle:
        uncompressed_bytes = len(handle.read())
    compression_ratio = uncompressed_bytes / compressed_bytes

    assert elapsed_ms < 500
    assert compression_ratio >= 3.0
