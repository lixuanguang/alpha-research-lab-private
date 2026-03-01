"""Validation tests for Data Plane fixture inventory."""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pyarrow.parquet as pq

_FIXTURE_ROOT = Path("tests/data/fixtures")
_REQUIRED_FIXTURES = [
    "sample_raw_trades.json",
    "sample_raw_books.json",
    "bad_trades.json",
    "bad_books.json",
    "gapped_trades.parquet",
]


def test_required_data_plane_fixture_files_exist() -> None:
    for fixture_name in _REQUIRED_FIXTURES:
        assert (_FIXTURE_ROOT / fixture_name).exists(), fixture_name


def test_json_fixtures_load_as_non_empty_lists() -> None:
    for fixture_name in _REQUIRED_FIXTURES:
        if not fixture_name.endswith(".json"):
            continue
        payload = json.loads((_FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8"))
        assert isinstance(payload, list)
        assert payload


def test_gapped_trades_fixture_contains_trade_time_gap() -> None:
    table = pq.read_table(_FIXTURE_ROOT / "gapped_trades.parquet")
    ts_event = sorted(table.column("ts_event").to_pylist())
    gaps = [
        (current - previous).total_seconds()
        for previous, current in pairwise(ts_event)
    ]
    assert any(gap > 300 for gap in gaps)
