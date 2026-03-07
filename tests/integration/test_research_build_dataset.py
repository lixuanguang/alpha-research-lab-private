"""Integration test: build-dataset CLI command end-to-end.

Verifies that the ``build-dataset`` command:
- Emits a planned outcome (plan-only mode, no filesystem writes).
- Calls DatasetBuilder, persists the manifest, and exits zero (execute mode).
- Outputs machine-readable JSON when ``--format json`` is requested.
- Fails fast with non-zero exit on invalid arguments.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import apps.research.main as research_main
import pyarrow as pa
import pytest
from click.testing import CliRunner

import alpha_core.instruments.master as master_mod
import alpha_core.instruments.models as instrument_models
import alpha_core.quality.gap_detector as gap_mod
import alpha_core.quality.partition_validator as pv_mod
import alpha_core.research.dataset_builder as builder_mod
import alpha_core.research.manifest as manifest_mod
import alpha_core.research.universe as universe_mod
import alpha_core.storage.parquet_reader as reader_mod

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
_END = _BASE + timedelta(days=7)
_START_STR = _BASE.strftime("%Y-%m-%dT%H:%M:%SZ")
_END_STR = _END.strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _silver_trades(n: int = 20) -> pa.Table:
    step = timedelta(minutes=30)
    ts_events = [_BASE + step * i for i in range(n)]
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
    instruments = [f"p:m1:{'yes' if i % 2 == 0 else 'no'}" for i in range(n)]
    return pa.table(
        {
            "event_id": [f"e{i}" for i in range(n)],
            "instrument_id": instruments,
            "venue_id": ["p"] * n,
            "event_type": ["trade"] * n,
            "ts_event": ts_events,
            "ts_record": ts_events,
            "price": [0.5] * n,
            "size": [100.0] * n,
        },
        schema=schema,
    )


def _make_wired_builder(tmp_path: Path) -> tuple[builder_mod.DatasetBuilder, Path]:
    master = master_mod.MarketMaster()
    master.register_market(_make_market("p", "m1", ["yes", "no"]))

    mock_reader = MagicMock(spec=reader_mod.ParquetEventReader)
    mock_reader.read_trades.return_value = _silver_trades()
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
    return builder, tmp_path


@pytest.fixture()
def wired_builder(tmp_path: Path) -> tuple[builder_mod.DatasetBuilder, Path]:
    """Return a (builder, storage_root) pair backed by synthetic silver data."""
    return _make_wired_builder(tmp_path)


# ---------------------------------------------------------------------------
# Tests — plan-only (no DatasetBuilder required)
# ---------------------------------------------------------------------------


def test_plan_only_exits_zero() -> None:
    """Plan-only mode must exit 0 and emit a planned outcome."""
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        ["build-dataset", "--name", "test_ds", "--start", _START_STR, "--end", _END_STR],
    )
    assert result.exit_code == 0, result.output
    assert "planned" in result.output


def test_plan_only_json_output() -> None:
    """JSON format plan-only output must be parseable with expected keys."""
    import json

    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "--format",
            "json",
            "build-dataset",
            "--name",
            "test_ds",
            "--start",
            _START_STR,
            "--end",
            _END_STR,
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "planned"
    assert data["run_type"] == "dataset_build"
    assert "run_id" in data
    assert "config_hash" in data


def test_execute_run_manifest_uses_same_config_hash_as_plan(tmp_path: Path) -> None:
    import json

    config_path = tmp_path / "dataset.yaml"
    config_path.write_text("research:\n  dataset:\n    mode: reproducible\n", encoding="utf-8")

    builder, storage_root = _make_wired_builder(tmp_path)
    runner = CliRunner()
    plan = runner.invoke(
        research_main.main,
        [
            "--format",
            "json",
            "--config",
            str(config_path),
            "build-dataset",
            "--name",
            "cfg_hash_match",
            "--start",
            _START_STR,
            "--end",
            _END_STR,
        ],
    )
    assert plan.exit_code == 0, plan.output
    planned_hash = json.loads(plan.output)["config_hash"]

    with patch("apps.research.commands.build_dataset.make_dataset_builder", return_value=builder):
        execute = runner.invoke(
            research_main.main,
            [
                "--config",
                str(config_path),
                "build-dataset",
                "--name",
                "cfg_hash_match",
                "--start",
                _START_STR,
                "--end",
                _END_STR,
                "--storage-root",
                str(storage_root),
                "--execute",
            ],
        )
    assert execute.exit_code == 0, execute.output
    run_dirs = sorted((storage_root / "runs").iterdir())
    run_manifest = manifest_mod.read_run_manifest(run_dirs[0] / "manifest.json")
    assert run_manifest.run.config_hash == planned_hash


# ---------------------------------------------------------------------------
# Tests — execute mode (DatasetBuilder is monkeypatched)
# ---------------------------------------------------------------------------


def test_execute_emits_materialized_status(
    wired_builder: tuple[builder_mod.DatasetBuilder, Path],
) -> None:
    """Execute mode must build the dataset and print a materialized outcome."""
    builder, storage_root = wired_builder
    runner = CliRunner()
    with patch("apps.research.commands.build_dataset.make_dataset_builder", return_value=builder):
        result = runner.invoke(
            research_main.main,
            [
                "build-dataset",
                "--name",
                "gold_jan",
                "--start",
                _START_STR,
                "--end",
                _END_STR,
                "--skip-quality-pass",
                "--storage-root",
                str(storage_root),
                "--execute",
            ],
        )
    assert result.exit_code == 0, result.output
    assert "materialized" in result.output


def test_execute_json_output_has_dataset_id(
    wired_builder: tuple[builder_mod.DatasetBuilder, Path],
) -> None:
    """JSON execute output must include dataset_id and window metadata."""
    import json

    builder, storage_root = wired_builder
    runner = CliRunner()
    with patch("apps.research.commands.build_dataset.make_dataset_builder", return_value=builder):
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "build-dataset",
                "--name",
                "gold_jan",
                "--start",
                _START_STR,
                "--end",
                _END_STR,
                "--skip-quality-pass",
                "--storage-root",
                str(storage_root),
                "--execute",
            ],
        )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "materialized"
    assert data["run_type"] == "dataset_build"
    assert "dataset_id" in data
    assert len(data["date_range"]) == 2
    assert "row_counts" in data
    assert "instrument_count" in data


def test_execute_writes_gold_parquet(
    wired_builder: tuple[builder_mod.DatasetBuilder, Path],
) -> None:
    """Gold trades.parquet must exist after a successful execute."""
    builder, storage_root = wired_builder
    runner = CliRunner()
    with patch("apps.research.commands.build_dataset.make_dataset_builder", return_value=builder):
        result = runner.invoke(
            research_main.main,
            [
                "build-dataset",
                "--name",
                "gold_parquet_check",
                "--start",
                _START_STR,
                "--end",
                _END_STR,
                "--event-type",
                "trades",
                "--skip-quality-pass",
                "--storage-root",
                str(storage_root),
                "--execute",
            ],
        )
    assert result.exit_code == 0, result.output
    gold_root = storage_root / "gold" / "datasets"
    dataset_dirs = list(gold_root.iterdir())
    assert len(dataset_dirs) == 1
    assert (dataset_dirs[0] / "trades.parquet").exists()


def test_execute_manifest_counts_match_silver(
    wired_builder: tuple[builder_mod.DatasetBuilder, Path],
) -> None:
    """Manifest row_counts must reflect rows written to gold parquet."""
    import json

    builder, storage_root = wired_builder
    runner = CliRunner()
    with patch("apps.research.commands.build_dataset.make_dataset_builder", return_value=builder):
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "build-dataset",
                "--name",
                "count_check",
                "--start",
                _START_STR,
                "--end",
                _END_STR,
                "--event-type",
                "trades",
                "--skip-quality-pass",
                "--storage-root",
                str(storage_root),
                "--execute",
            ],
        )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    trades_count = data["row_counts"].get("trades", 0)
    # Expect the 20 synthetic rows we injected via _silver_trades().
    assert trades_count == 20


def test_execute_json_output_has_run_id(
    wired_builder: tuple[builder_mod.DatasetBuilder, Path],
) -> None:
    import json

    builder, storage_root = wired_builder
    runner = CliRunner()
    with patch("apps.research.commands.build_dataset.make_dataset_builder", return_value=builder):
        result = runner.invoke(
            research_main.main,
            [
                "--format",
                "json",
                "build-dataset",
                "--name",
                "run_id_check",
                "--start",
                _START_STR,
                "--end",
                _END_STR,
                "--skip-quality-pass",
                "--storage-root",
                str(storage_root),
                "--execute",
            ],
        )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["run_id"]


def test_execute_manifest_parent_run_id_is_set(
    wired_builder: tuple[builder_mod.DatasetBuilder, Path],
) -> None:
    builder, storage_root = wired_builder
    runner = CliRunner()
    with patch("apps.research.commands.build_dataset.make_dataset_builder", return_value=builder):
        result = runner.invoke(
            research_main.main,
            [
                "build-dataset",
                "--name",
                "lineage_check",
                "--start",
                _START_STR,
                "--end",
                _END_STR,
                "--skip-quality-pass",
                "--parent-run-id",
                "ingestion_run_123",
                "--storage-root",
                str(storage_root),
                "--execute",
            ],
        )
    assert result.exit_code == 0, result.output
    run_dirs = sorted((storage_root / "runs").iterdir())
    run_manifest = manifest_mod.read_run_manifest(run_dirs[0] / "manifest.json")
    assert run_manifest.parent_run_id == "ingestion_run_123"


# ---------------------------------------------------------------------------
# Tests — error paths
# ---------------------------------------------------------------------------


def test_invalid_max_gap_hours_exits_nonzero() -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "build-dataset",
            "--name",
            "bad",
            "--start",
            _START_STR,
            "--end",
            _END_STR,
            "--max-gap-hours",
            "0",
        ],
    )
    assert result.exit_code != 0


def test_invalid_start_datetime_exits_nonzero() -> None:
    runner = CliRunner()
    result = runner.invoke(
        research_main.main,
        [
            "build-dataset",
            "--name",
            "bad",
            "--start",
            "not-a-date",
            "--end",
            _END_STR,
        ],
    )
    assert result.exit_code != 0


def test_dataset_build_error_exits_nonzero(
    wired_builder: tuple[builder_mod.DatasetBuilder, Path],
) -> None:
    """DatasetBuildError (e.g. quality gate failure) must exit non-zero."""
    _builder, storage_root = wired_builder

    def _failing_builder(_root: Path) -> builder_mod.DatasetBuilder:
        failing = MagicMock(spec=builder_mod.DatasetBuilder)
        failing.build.side_effect = builder_mod.DatasetBuildError("quality gate failed")
        return failing

    runner = CliRunner()
    with patch(
        "apps.research.commands.build_dataset.make_dataset_builder",
        side_effect=_failing_builder,
    ):
        result = runner.invoke(
            research_main.main,
            [
                "build-dataset",
                "--name",
                "bad_quality",
                "--start",
                _START_STR,
                "--end",
                _END_STR,
                "--skip-quality-pass",
                "--storage-root",
                str(storage_root),
                "--execute",
            ],
        )
    assert result.exit_code != 0
    assert "quality gate failed" in result.output
