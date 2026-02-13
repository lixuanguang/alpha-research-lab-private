"""Regression tests for deterministic data snapshot manifests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from lab.data.snapshot import create_data_snapshot


def _write_close(path: Path, *, scale: float = 1.0) -> None:
    idx = pd.bdate_range("2024-01-02", periods=10)
    close = pd.DataFrame(
        {
            "SPY": (100.0 + np.linspace(0.0, 2.0, len(idx))) * scale,
            "TLT": (90.0 + np.linspace(0.0, 1.0, len(idx))) * scale,
        },
        index=idx,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    close.to_parquet(path)


def _write_macro(path: Path, *, shift: float = 0.0) -> None:
    idx = pd.to_datetime(["2024-01-01", "2024-02-01", "2024-03-01"])
    series = pd.DataFrame({"value": [3.7 + shift, 3.8 + shift, 3.9 + shift]}, index=idx)
    path.parent.mkdir(parents=True, exist_ok=True)
    series.to_parquet(path)


def _snapshot(
    *,
    data_root: Path,
    close_path: Path,
    macro_paths: list[Path],
) -> tuple[str, Path, dict[str, object]]:
    return create_data_snapshot(
        source_name="yf",
        tickers=["SPY", "TLT"],
        start="2024-01-01",
        end="2024-03-31",
        adjustment_policy={"auto_adjust": True, "group_by": "ticker", "threads": False},
        close_path=close_path,
        macro_files=macro_paths,
        root=data_root / "snapshots",
    )


def test_snapshot_changes_when_price_or_macro_files_change(tmp_path: Path) -> None:
    close_path = tmp_path / "prices" / "close.parquet"
    macro_path = tmp_path / "macro" / "fred" / "UNRATE.parquet"

    _write_close(close_path, scale=1.0)
    _write_macro(macro_path, shift=0.0)
    snap_1, _, _ = _snapshot(
        data_root=tmp_path,
        close_path=close_path,
        macro_paths=[macro_path],
    )

    _write_close(close_path, scale=1.01)
    snap_2, _, _ = _snapshot(
        data_root=tmp_path,
        close_path=close_path,
        macro_paths=[macro_path],
    )
    assert snap_1 != snap_2

    _write_close(close_path, scale=1.0)
    _write_macro(macro_path, shift=0.25)
    snap_3, _, _ = _snapshot(
        data_root=tmp_path,
        close_path=close_path,
        macro_paths=[macro_path],
    )
    assert snap_1 != snap_3


def test_snapshot_is_reproducible_for_same_inputs(tmp_path: Path) -> None:
    close_path = tmp_path / "prices" / "close.parquet"
    macro_path = tmp_path / "macro" / "fred" / "UNRATE.parquet"

    _write_close(close_path, scale=1.0)
    _write_macro(macro_path, shift=0.0)

    snap_1, manifest_path_1, manifest_1 = _snapshot(
        data_root=tmp_path,
        close_path=close_path,
        macro_paths=[macro_path],
    )
    snap_2, manifest_path_2, manifest_2 = _snapshot(
        data_root=tmp_path,
        close_path=close_path,
        macro_paths=[macro_path],
    )

    assert snap_1 == snap_2
    assert manifest_path_1 == manifest_path_2
    assert manifest_path_1.exists()
    assert manifest_1["hashes"] == manifest_2["hashes"]
