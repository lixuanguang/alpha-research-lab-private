"""Week-3 macro ingestion and lagging acceptance tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lab.data.adapters.fred import load_fred, require_fred_api_key
from lab.features.macro.macro_lag import apply_observation_lag


def _write_fred_series(root: Path, series_id: str, values: pd.Series) -> None:
    root.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({"value": values.astype(float)}, index=pd.DatetimeIndex(values.index))
    df.to_parquet(root / f"{series_id}.parquet")


def test_fred_api_key_missing_raises_clean_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="Missing FRED_API_KEY"):
        require_fred_api_key()


def test_load_fred_aligns_requested_series_to_single_date_index(tmp_path: Path) -> None:
    root = tmp_path / "macro" / "fred"
    idx_a = pd.to_datetime(["2024-01-01", "2024-01-08", "2024-01-15"])
    idx_b = pd.to_datetime(["2024-01-03", "2024-01-10", "2024-01-17"])
    _write_fred_series(root, "CPIAUCSL", pd.Series([300.0, 301.0, 302.0], index=idx_a))
    _write_fred_series(root, "UNRATE", pd.Series([3.8, 3.9, 4.0], index=idx_b))

    panel = load_fred(["CPIAUCSL", "UNRATE"], "2024-01-01", "2024-01-31", root=root)

    assert list(panel.columns) == ["CPIAUCSL", "UNRATE"]
    assert panel.index.is_monotonic_increasing
    assert panel.index.is_unique
    assert panel.index.min() == pd.Timestamp("2024-01-01")
    assert panel.index.max() == pd.Timestamp("2024-01-17")


def test_apply_observation_lag_enforces_known_at_time_cutoff() -> None:
    obs_idx = pd.to_datetime(["2024-01-01", "2024-01-15", "2024-02-01"])
    raw = pd.DataFrame({"CPIAUCSL": [300.0, 301.0, 302.0]}, index=obs_idx)
    calendar = pd.bdate_range("2024-01-01", "2024-03-15")

    lag_days = 30
    lagged = apply_observation_lag(
        raw,
        lag_days=lag_days,
        calendar_index=calendar,
        backfill_limit=0,
    )

    assert lagged.index.equals(calendar)
    non_null = lagged["CPIAUCSL"].dropna()
    assert not non_null.empty
    assert non_null.index.min() >= obs_idx.min() + pd.Timedelta(days=lag_days)

    for when, value in non_null.items():
        valid_obs = raw.index[raw.index <= when - pd.Timedelta(days=lag_days)]
        assert len(valid_obs) > 0
        latest_obs = valid_obs.max()
        assert value == pytest.approx(float(raw.loc[latest_obs, "CPIAUCSL"]))


def test_apply_observation_lag_avoids_forward_fill_and_only_short_backfills() -> None:
    obs_idx = pd.to_datetime(["2024-01-01", "2024-02-01"])
    raw = pd.DataFrame({"DFF": [5.25, 5.00]}, index=obs_idx)
    calendar = pd.bdate_range("2024-01-01", "2024-02-20")

    lagged = apply_observation_lag(
        raw,
        lag_days=10,
        calendar_index=calendar,
        backfill_limit=2,
    )

    # After lagging, first availability is 2024-01-11; only 2 days before can be bfilled.
    assert lagged.loc[pd.Timestamp("2024-01-09"), "DFF"] == pytest.approx(5.25)
    assert lagged.loc[pd.Timestamp("2024-01-10"), "DFF"] == pytest.approx(5.25)
    # No forward-fill across long gaps after a known date.
    assert np.isnan(lagged.loc[pd.Timestamp("2024-01-12"), "DFF"])
