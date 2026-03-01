"""Unit tests for OutcomeSelector."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import apps.data_collector.connectors.outcome_selector as outcome_selector_mod

import alpha_core.instruments.master as instruments_master
import alpha_core.instruments.models as instrument_models

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _market(
    market_id: str,
    *,
    venue: str = "kalshi",
    lifecycle: instrument_models.MarketLifecycle = instrument_models.MarketLifecycle.ACTIVE,
    volume: Decimal | None = None,
    liquidity: Decimal | None = None,
    outcomes: list[str] | None = None,
) -> instrument_models.MarketSpec:
    outcome_ids = outcomes or [f"{market_id}_yes"]
    return instrument_models.MarketSpec(
        market_id=market_id,
        venue=venue,
        title=f"Market {market_id}",
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
        first_seen=_NOW,
        last_updated=_NOW,
    )


def _master(*markets: instrument_models.MarketSpec) -> instruments_master.MarketMaster:
    master = instruments_master.MarketMaster()
    for m in markets:
        master.register_market(m)
    return master


# ---------------------------------------------------------------------------
# Basic selection
# ---------------------------------------------------------------------------


def test_selects_active_outcomes_by_default() -> None:
    master = _master(
        _market("m1"),
        _market("m2"),
    )
    selector = outcome_selector_mod.OutcomeSelector(master)
    ids = selector.select("kalshi")
    assert len(ids) == 2
    assert all("kalshi:m" in cid for cid in ids)


def test_empty_master_returns_empty() -> None:
    master = instruments_master.MarketMaster()
    selector = outcome_selector_mod.OutcomeSelector(master)
    assert selector.select("kalshi") == []


def test_wrong_venue_returns_empty() -> None:
    master = _master(_market("m1", venue="kalshi"))
    selector = outcome_selector_mod.OutcomeSelector(master)
    assert selector.select("polymarket") == []


# ---------------------------------------------------------------------------
# Lifecycle filter
# ---------------------------------------------------------------------------


def test_lifecycle_filter_excludes_halted() -> None:
    master = _master(
        _market("active", lifecycle=instrument_models.MarketLifecycle.ACTIVE),
        _market("halted", lifecycle=instrument_models.MarketLifecycle.HALTED),
    )
    selector = outcome_selector_mod.OutcomeSelector(
        master,
        lifecycle_filter=[instrument_models.MarketLifecycle.ACTIVE],
    )
    ids = selector.select("kalshi")
    assert len(ids) == 1
    assert "active" in ids[0]


def test_lifecycle_filter_includes_multiple_states() -> None:
    master = _master(
        _market("active", lifecycle=instrument_models.MarketLifecycle.ACTIVE),
        _market("halted", lifecycle=instrument_models.MarketLifecycle.HALTED),
        _market("resolved", lifecycle=instrument_models.MarketLifecycle.RESOLVED),
    )
    selector = outcome_selector_mod.OutcomeSelector(
        master,
        lifecycle_filter=[
            instrument_models.MarketLifecycle.ACTIVE,
            instrument_models.MarketLifecycle.HALTED,
        ],
    )
    ids = selector.select("kalshi")
    assert len(ids) == 2


# ---------------------------------------------------------------------------
# Volume filter
# ---------------------------------------------------------------------------


def test_min_volume_filters_low_volume() -> None:
    master = _master(
        _market("high", volume=Decimal("500")),
        _market("low", volume=Decimal("50")),
    )
    selector = outcome_selector_mod.OutcomeSelector(master, min_volume=Decimal("100"))
    ids = selector.select("kalshi")
    assert len(ids) == 1
    assert "high" in ids[0]


def test_none_volume_always_passes() -> None:
    master = _master(_market("novolume", volume=None))
    selector = outcome_selector_mod.OutcomeSelector(master, min_volume=Decimal("1000"))
    ids = selector.select("kalshi")
    assert len(ids) == 1


# ---------------------------------------------------------------------------
# Liquidity filter
# ---------------------------------------------------------------------------


def test_min_liquidity_filters() -> None:
    master = _master(
        _market("liquid", liquidity=Decimal("200")),
        _market("dry", liquidity=Decimal("5")),
    )
    selector = outcome_selector_mod.OutcomeSelector(master, min_liquidity=Decimal("100"))
    ids = selector.select("kalshi")
    assert len(ids) == 1
    assert "liquid" in ids[0]


def test_none_liquidity_always_passes() -> None:
    master = _master(_market("noliq", liquidity=None))
    selector = outcome_selector_mod.OutcomeSelector(master, min_liquidity=Decimal("9999"))
    ids = selector.select("kalshi")
    assert len(ids) == 1


# ---------------------------------------------------------------------------
# Combined filters + return sorted
# ---------------------------------------------------------------------------


def test_combined_filters() -> None:
    master = _master(
        _market("pass", volume=Decimal("200"), liquidity=Decimal("50")),
        _market("fail_vol", volume=Decimal("10"), liquidity=Decimal("50")),
        _market("fail_liq", volume=Decimal("200"), liquidity=Decimal("1")),
    )
    selector = outcome_selector_mod.OutcomeSelector(
        master,
        min_volume=Decimal("100"),
        min_liquidity=Decimal("20"),
    )
    ids = selector.select("kalshi")
    assert len(ids) == 1
    assert "pass" in ids[0]


def test_result_is_sorted() -> None:
    master = _master(
        _market("zzz"),
        _market("aaa"),
        _market("mmm"),
    )
    selector = outcome_selector_mod.OutcomeSelector(master)
    ids = selector.select("kalshi")
    assert ids == sorted(ids)
