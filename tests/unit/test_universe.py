"""Unit tests for UniverseManager and UniverseSnapshot."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import alpha_core.instruments.master as master_mod
import alpha_core.instruments.models as instrument_models
import alpha_core.research.universe as universe_mod

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_master() -> master_mod.MarketMaster:
    return master_mod.MarketMaster()


def _make_market(
    venue: str,
    market_id: str,
    outcome_ids: list[str],
    *,
    lifecycle: instrument_models.MarketLifecycle = instrument_models.MarketLifecycle.ACTIVE,
    volume: Decimal | None = None,
    liquidity: Decimal | None = None,
    first_seen: datetime | None = None,
    last_updated: datetime | None = None,
    resolution_date: datetime | None = None,
) -> instrument_models.MarketSpec:
    now = datetime.now(tz=UTC)
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
            for oid in outcome_ids
        ],
        lifecycle=lifecycle,
        volume=volume,
        liquidity=liquidity,
        first_seen=first_seen or now,
        last_updated=last_updated or now,
        resolution_date=resolution_date,
    )


_BASE = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
_DAY = timedelta(days=1)


# ---------------------------------------------------------------------------
# UniverseManager.snapshot_at
# ---------------------------------------------------------------------------


class TestSnapshotAt:
    def test_returns_markets_known_at_time(self) -> None:
        master = _make_master()
        master.register_market(_make_market("polymarket", "m1", ["yes", "no"], first_seen=_BASE))
        master.register_market(_make_market("polymarket", "m2", ["a"], first_seen=_BASE + 5 * _DAY))
        mgr = universe_mod.UniverseManager(master)
        snap = mgr.snapshot_at(_BASE + 2 * _DAY)
        assert "polymarket:m1:yes" in snap.instruments
        assert "polymarket:m1:no" in snap.instruments
        assert "polymarket:m2:a" not in snap.instruments

    def test_excludes_markets_not_yet_seen(self) -> None:
        master = _make_master()
        master.register_market(_make_market("kalshi", "m1", ["yes"], first_seen=_BASE + 10 * _DAY))
        mgr = universe_mod.UniverseManager(master)
        snap = mgr.snapshot_at(_BASE)
        assert snap.instruments == []
        assert snap.markets == []

    def test_filters_by_lifecycle(self) -> None:
        master = _make_master()
        master.register_market(
            _make_market(
                "p",
                "active_mkt",
                ["yes"],
                lifecycle=instrument_models.MarketLifecycle.ACTIVE,
                first_seen=_BASE,
            )
        )
        master.register_market(
            _make_market(
                "p",
                "halted_mkt",
                ["yes"],
                lifecycle=instrument_models.MarketLifecycle.HALTED,
                first_seen=_BASE,
            )
        )
        mgr = universe_mod.UniverseManager(
            master,
            lifecycle_filter=[instrument_models.MarketLifecycle.ACTIVE],
        )
        snap = mgr.snapshot_at(_BASE + _DAY)
        assert "p:active_mkt:yes" in snap.instruments
        assert "p:halted_mkt:yes" not in snap.instruments

    def test_filters_by_min_volume(self) -> None:
        master = _make_master()
        master.register_market(
            _make_market("p", "low", ["y"], volume=Decimal("50"), first_seen=_BASE)
        )
        master.register_market(
            _make_market("p", "high", ["y"], volume=Decimal("1000"), first_seen=_BASE)
        )
        mgr = universe_mod.UniverseManager(master, min_volume=Decimal("100"))
        snap = mgr.snapshot_at(_BASE + _DAY)
        assert "p:high:y" in snap.instruments
        assert "p:low:y" not in snap.instruments

    def test_filters_by_min_liquidity(self) -> None:
        master = _make_master()
        master.register_market(
            _make_market("p", "illiquid", ["y"], liquidity=Decimal("5"), first_seen=_BASE)
        )
        master.register_market(
            _make_market("p", "liquid", ["y"], liquidity=Decimal("500"), first_seen=_BASE)
        )
        mgr = universe_mod.UniverseManager(master, min_liquidity=Decimal("100"))
        snap = mgr.snapshot_at(_BASE + _DAY)
        assert "p:liquid:y" in snap.instruments
        assert "p:illiquid:y" not in snap.instruments

    def test_filters_by_venue(self) -> None:
        master = _make_master()
        master.register_market(_make_market("polymarket", "m1", ["y"], first_seen=_BASE))
        master.register_market(_make_market("kalshi", "m2", ["y"], first_seen=_BASE))
        mgr = universe_mod.UniverseManager(master, venues=["polymarket"])
        snap = mgr.snapshot_at(_BASE + _DAY)
        assert "polymarket:m1:y" in snap.instruments
        assert "kalshi:m2:y" not in snap.instruments

    def test_venue_breakdown(self) -> None:
        master = _make_master()
        master.register_market(_make_market("v1", "m1", ["a", "b"], first_seen=_BASE))
        master.register_market(_make_market("v2", "m2", ["x"], first_seen=_BASE))
        mgr = universe_mod.UniverseManager(master)
        snap = mgr.snapshot_at(_BASE + _DAY)
        assert snap.venue_breakdown.get("v1", 0) == 2
        assert snap.venue_breakdown.get("v2", 0) == 1

    def test_resolved_market_treated_as_active_before_resolution_date(self) -> None:
        """A RESOLVED market whose resolution_date is after as_of was active at that time."""
        resolution_dt = _BASE + 10 * _DAY
        master = _make_master()
        master.register_market(
            _make_market(
                "p",
                "m1",
                ["y"],
                lifecycle=instrument_models.MarketLifecycle.RESOLVED,
                resolution_date=resolution_dt,
                first_seen=_BASE,
            )
        )
        mgr = universe_mod.UniverseManager(
            master,
            lifecycle_filter=[instrument_models.MarketLifecycle.ACTIVE],
        )
        # Before resolution: should appear
        snap_before = mgr.snapshot_at(_BASE + _DAY)
        assert "p:m1:y" in snap_before.instruments

        # After resolution: should NOT appear (lifecycle filter == ACTIVE)
        snap_after = mgr.snapshot_at(_BASE + 11 * _DAY)
        assert "p:m1:y" not in snap_after.instruments

    def test_empty_master_returns_empty_snapshot(self) -> None:
        master = _make_master()
        mgr = universe_mod.UniverseManager(master)
        snap = mgr.snapshot_at(_BASE)
        assert snap.instruments == []
        assert snap.markets == []

    def test_snapshot_as_of_matches_requested_time(self) -> None:
        master = _make_master()
        mgr = universe_mod.UniverseManager(master)
        as_of = _BASE + 3 * _DAY
        snap = mgr.snapshot_at(as_of)
        assert snap.as_of == as_of

    def test_filters_applied_recorded(self) -> None:
        master = _make_master()
        mgr = universe_mod.UniverseManager(
            master,
            min_volume=Decimal("10"),
            venues=["polymarket"],
        )
        snap = mgr.snapshot_at(_BASE)
        assert snap.filters_applied["min_volume"] == "10"
        assert snap.filters_applied["venues"] == ["polymarket"]


# ---------------------------------------------------------------------------
# UniverseManager.time_series
# ---------------------------------------------------------------------------


class TestTimeSeries:
    def test_returns_list_of_snapshots(self) -> None:
        master = _make_master()
        master.register_market(_make_market("p", "m1", ["y"], first_seen=_BASE))
        mgr = universe_mod.UniverseManager(master)
        series = mgr.time_series(_BASE, _BASE + 3 * _DAY, frequency="1d")
        # 4 grid points: D0, D1, D2, D3
        assert len(series) == 4

    def test_series_respects_point_in_time_per_snapshot(self) -> None:
        master = _make_master()
        master.register_market(_make_market("p", "early", ["y"], first_seen=_BASE))
        master.register_market(_make_market("p", "late", ["y"], first_seen=_BASE + 2 * _DAY))
        mgr = universe_mod.UniverseManager(master)
        series = mgr.time_series(_BASE, _BASE + 3 * _DAY, frequency="1d")
        # D0 has only "early"
        assert "p:early:y" in series[0].instruments
        assert "p:late:y" not in series[0].instruments
        # D2+ has both
        assert "p:late:y" in series[2].instruments

    def test_single_day_returns_one_snapshot(self) -> None:
        master = _make_master()
        mgr = universe_mod.UniverseManager(master)
        series = mgr.time_series(_BASE, _BASE, frequency="1d")
        assert len(series) == 1
