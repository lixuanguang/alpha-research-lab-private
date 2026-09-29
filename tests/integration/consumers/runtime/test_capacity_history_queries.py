"""Keep cache classes and underpowered cold-query samples distinct."""

from __future__ import annotations

# standard library imports
from pathlib import Path

# third party library imports
import pytest
from capacity_history_queries import CapacityHistoryQueries


class TestCapacityHistoryQueries:
    """Require sufficient exact observations for each separately declared cache boundary."""

    def test_cold_percentiles_require_1000_actual_observations(self) -> None:
        """A short pilot supplies a range and cannot claim the cold query target."""
        short = CapacityHistoryQueries._summarize((2_500_000_000,) * 999, (2_000_000_000,) * 3)
        assert short["status"] == "unmeasured"
        assert "p99_ns" not in short
        complete = CapacityHistoryQueries._summarize((2_500_000_000,) * 1000, (2_000_000_000,) * 3)
        assert complete["status"] == "fail"
        assert complete["p99_ns"] == 2_500_000_000
        warm = CapacityHistoryQueries._summarize((1_000_000,) * 1000, (50_000_000,) * 3)
        assert warm["status"] == "pass"
        assert complete["status"] == "fail"

    def test_dashboard_readers_are_joined_by_their_own_schedule(self) -> None:
        """Waiting follows each reader's paced budget, not the depth readers' finish."""
        start = 1_000_000_000
        cold = CapacityHistoryQueries._reader_deadline_ns(start, 250, "application_cold")
        warm = CapacityHistoryQueries._reader_deadline_ns(start, 250, "warm")
        assert cold - start == 250 * 3_000_000_000 + 30_000_000_000
        assert warm - start == 250 * 1_000_000_000 + 30_000_000_000
        # The stopped cohort's slowest cold dashboard request took 0.956 s.
        assert cold - start > 250 * 956_000_000

    def test_missing_identity_and_invented_duration_fail(self) -> None:
        """Neither changed result bytes nor a missing monotonic duration can be counted."""
        with pytest.raises(ValueError, match="exact result identity"):
            CapacityHistoryQueries._identity({"returned_bytes": 100})
        with pytest.raises(ValueError, match="invalid retained query duration"):
            CapacityHistoryQueries._integer({"service_ns": None}, "service_ns")

    def test_limits_are_declared_before_reading_trial(self, tmp_path: Path) -> None:
        """Refuse an excessive authored query fixture without opening unavailable history."""
        with pytest.raises(ValueError, match="query boundary"):
            CapacityHistoryQueries(
                tmp_path / "trial",
                tmp_path / "output",
                samples_per_reader=250,
                dashboard_events_per_account=10_001,
            )
