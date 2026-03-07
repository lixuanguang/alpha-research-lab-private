"""Unit tests for instrument models, symbology, lifecycle, and market master."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import alpha_core.instruments.lifecycle as lifecycle_utils
import alpha_core.instruments.master as instruments_master
import alpha_core.instruments.models as instrument_models
import alpha_core.instruments.symbology as symbology


def _fixture_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "fixtures" / "sample_markets.json"


def _load_market_specs() -> list[instrument_models.MarketSpec]:
    payload = json.loads(_fixture_path().read_text(encoding="utf-8"))
    return [instrument_models.MarketSpec.model_validate(item) for item in payload]


class _MockAdapter:
    def __init__(self, markets: Sequence[instrument_models.MarketSpec]) -> None:
        self._markets = list(markets)

    async def fetch_markets(self) -> list[instrument_models.MarketSpec]:
        return self._markets


def test_market_spec_validates_from_fixture_data() -> None:
    market = _load_market_specs()[0]

    assert market.venue == "polymarket"
    assert market.lifecycle == instrument_models.MarketLifecycle.ACTIVE
    assert market.first_seen.tzinfo == UTC


def test_market_spec_rejects_last_updated_before_first_seen() -> None:
    market = _load_market_specs()[0].model_dump(mode="python")
    market["last_updated"] = datetime(2026, 1, 1, tzinfo=UTC)
    market["first_seen"] = datetime(2026, 2, 1, tzinfo=UTC)

    with pytest.raises(ValidationError, match="last_updated"):
        instrument_models.MarketSpec.model_validate(market)


def test_canonical_outcome_id_format_and_parse_are_consistent() -> None:
    canonical = symbology.make_canonical_outcome_id("Polymarket", "mkt-1", "yes")

    assert canonical == "polymarket:mkt-1:yes"
    assert symbology.parse_canonical_outcome_id(canonical) == ("polymarket", "mkt-1", "yes")


def test_parse_canonical_outcome_id_rejects_invalid_format() -> None:
    with pytest.raises(ValueError, match="expected"):
        symbology.parse_canonical_outcome_id("polymarket:mkt-1")


def test_lifecycle_transition_allows_active_to_halted() -> None:
    assert (
        lifecycle_utils.can_transition(
            instrument_models.MarketLifecycle.ACTIVE,
            instrument_models.MarketLifecycle.HALTED,
        )
        is True
    )
    lifecycle_utils.validate_transition(
        instrument_models.MarketLifecycle.ACTIVE,
        instrument_models.MarketLifecycle.HALTED,
    )


def test_lifecycle_transition_rejects_resolved_to_active() -> None:
    assert (
        lifecycle_utils.can_transition(
            instrument_models.MarketLifecycle.RESOLVED,
            instrument_models.MarketLifecycle.ACTIVE,
        )
        is False
    )
    with pytest.raises(ValueError, match="Invalid lifecycle transition"):
        lifecycle_utils.validate_transition(
            instrument_models.MarketLifecycle.RESOLVED,
            instrument_models.MarketLifecycle.ACTIVE,
        )


def test_market_master_load_and_get_lookups() -> None:
    master = instruments_master.MarketMaster()
    markets = _load_market_specs()

    loaded = asyncio.run(master.load_from_exchange(_MockAdapter(markets)))

    assert loaded == len(markets)
    market = master.get_market("polymarket:us-pres-2028-winner")
    assert market is not None
    assert market.title.startswith("Who will win")
    outcome = master.get_outcome("polymarket:us-pres-2028-winner:yes")
    assert outcome is not None
    assert outcome.label == "Yes"


def test_market_master_get_market_returns_defensive_copy() -> None:
    master = instruments_master.MarketMaster()
    asyncio.run(master.load_from_exchange(_MockAdapter(_load_market_specs())))

    canonical_market_id = "polymarket:us-pres-2028-winner"
    market = master.get_market(canonical_market_id)
    assert market is not None

    market.title = "Mutated title"
    unchanged = master.get_market(canonical_market_id)

    assert unchanged is not None
    assert unchanged.title == "Who will win the 2028 US presidential election?"


def test_market_master_get_outcome_returns_defensive_copy() -> None:
    master = instruments_master.MarketMaster()
    asyncio.run(master.load_from_exchange(_MockAdapter(_load_market_specs())))

    canonical_outcome_id = "polymarket:us-pres-2028-winner:yes"
    outcome = master.get_outcome(canonical_outcome_id)
    assert outcome is not None

    outcome.label = "Mutated label"
    unchanged = master.get_outcome(canonical_outcome_id)

    assert unchanged is not None
    assert unchanged.label == "Yes"


def test_market_master_search_returns_defensive_copies() -> None:
    master = instruments_master.MarketMaster()
    asyncio.run(master.load_from_exchange(_MockAdapter(_load_market_specs())))

    results = master.search(venue="polymarket")
    assert results
    results[0].title = "Mutated title from search"

    refreshed = master.search(venue="polymarket")
    assert refreshed[0].title != "Mutated title from search"


def test_market_master_register_market_replaces_stale_outcomes() -> None:
    master = instruments_master.MarketMaster()
    original_market = _load_market_specs()[0]
    master.register_market(original_market)

    updated_payload = original_market.model_dump(mode="python")
    updated_payload["outcomes"] = [
        {
            "outcome_id": "yes",
            "label": "Yes",
            "canonical_id": "polymarket:us-pres-2028-winner:yes",
        }
    ]
    updated_market = instrument_models.MarketSpec.model_validate(updated_payload)
    master.register_market(updated_market)

    assert master.get_outcome("polymarket:us-pres-2028-winner:yes") is not None
    assert master.get_outcome("polymarket:us-pres-2028-winner:no") is None
    assert master.snapshot()["outcome_count"] == 1


def test_market_master_register_market_preserves_first_seen_and_latest_last_updated() -> None:
    master = instruments_master.MarketMaster()
    original_market = _load_market_specs()[0].model_copy(
        update={
            "first_seen": datetime(2026, 2, 1, tzinfo=UTC),
            "last_updated": datetime(2026, 2, 2, tzinfo=UTC),
        }
    )
    master.register_market(original_market)

    refreshed_market = original_market.model_copy(
        update={
            "first_seen": datetime(2026, 2, 10, tzinfo=UTC),
            "last_updated": datetime(2026, 2, 11, tzinfo=UTC),
        }
    )
    master.register_market(refreshed_market)

    older_refresh = original_market.model_copy(
        update={"last_updated": datetime(2026, 2, 5, tzinfo=UTC)}
    )
    master.register_market(older_refresh)

    stored = master.get_market("polymarket:us-pres-2028-winner")
    assert stored is not None
    assert stored.first_seen == datetime(2026, 2, 1, tzinfo=UTC)
    assert stored.last_updated == datetime(2026, 2, 11, tzinfo=UTC)


def test_market_master_current_snapshot_keeps_latest_payload_fields() -> None:
    master = instruments_master.MarketMaster()
    original_market = _load_market_specs()[0].model_copy(
        update={
            "title": "Original title",
            "last_updated": datetime(2026, 2, 2, tzinfo=UTC),
        }
    )
    latest_market = original_market.model_copy(
        update={
            "title": "Latest title",
            "last_updated": datetime(2026, 2, 11, tzinfo=UTC),
        }
    )
    stale_refresh = original_market.model_copy(
        update={
            "title": "Stale title",
            "last_updated": datetime(2026, 2, 5, tzinfo=UTC),
        }
    )

    master.register_market(original_market)
    master.register_market(latest_market)
    master.register_market(stale_refresh)

    stored = master.get_market("polymarket:us-pres-2028-winner")
    assert stored is not None
    assert stored.title == "Latest title"


def test_market_master_market_at_uses_history() -> None:
    master = instruments_master.MarketMaster()
    market = _load_market_specs()[0].model_copy(
        update={
            "volume": 10,
            "first_seen": datetime(2026, 2, 1, tzinfo=UTC),
            "last_updated": datetime(2026, 2, 1, tzinfo=UTC),
        }
    )
    master.register_market(market)
    master.register_market(
        market.model_copy(
            update={
                "volume": 99,
                "last_updated": datetime(2026, 2, 4, tzinfo=UTC),
            }
        )
    )

    early = master.market_at(
        "polymarket:us-pres-2028-winner",
        datetime(2026, 2, 2, tzinfo=UTC),
    )
    late = master.market_at(
        "polymarket:us-pres-2028-winner",
        datetime(2026, 2, 5, tzinfo=UTC),
    )

    assert early is not None
    assert late is not None
    assert early.volume == 10
    assert late.volume == 99


def test_market_master_backfilled_history_updates_first_seen_across_versions() -> None:
    master = instruments_master.MarketMaster()
    market = _load_market_specs()[0].model_copy(
        update={
            "first_seen": datetime(2026, 2, 5, tzinfo=UTC),
            "last_updated": datetime(2026, 2, 5, tzinfo=UTC),
        }
    )
    master.register_market(market)
    master.register_market(
        market.model_copy(
            update={
                "first_seen": datetime(2026, 2, 1, tzinfo=UTC),
                "last_updated": datetime(2026, 2, 1, tzinfo=UTC),
            }
        )
    )

    history = master.get_market_history("polymarket:us-pres-2028-winner")

    assert history
    assert all(item.first_seen == datetime(2026, 2, 1, tzinfo=UTC) for item in history)


def test_market_master_search_filters_by_venue_category_and_lifecycle() -> None:
    master = instruments_master.MarketMaster()
    asyncio.run(master.load_from_exchange(_MockAdapter(_load_market_specs())))

    by_venue = master.search(venue="polymarket")
    by_category = master.search(category="politics")
    by_lifecycle = master.search(lifecycle=instrument_models.MarketLifecycle.HALTED)

    assert len(by_venue) == 4
    assert len(by_category) == 3
    assert len(by_lifecycle) == 1
    assert by_lifecycle[0].market_id == "btc-above-100k-2026"


def test_market_master_search_matches_text_query() -> None:
    master = instruments_master.MarketMaster()
    asyncio.run(master.load_from_exchange(_MockAdapter(_load_market_specs())))

    results = master.search(query="threshold")

    assert len(results) == 1
    assert results[0].category == "crypto"


def test_market_master_update_lifecycle_enforces_state_machine() -> None:
    master = instruments_master.MarketMaster()
    asyncio.run(master.load_from_exchange(_MockAdapter(_load_market_specs())))

    canonical_market_id = "polymarket:btc-above-100k-2026"
    master.update_lifecycle(canonical_market_id, instrument_models.MarketLifecycle.RESOLVED)

    updated_market = master.get_market(canonical_market_id)
    assert updated_market is not None
    assert updated_market.lifecycle == instrument_models.MarketLifecycle.RESOLVED

    with pytest.raises(ValueError, match="Invalid lifecycle transition"):
        master.update_lifecycle(canonical_market_id, instrument_models.MarketLifecycle.ACTIVE)


def test_market_master_snapshot_is_deterministic() -> None:
    markets = _load_market_specs()

    first = instruments_master.MarketMaster()
    second = instruments_master.MarketMaster()
    asyncio.run(first.load_from_exchange(_MockAdapter(markets)))
    asyncio.run(second.load_from_exchange(_MockAdapter(list(reversed(markets)))))

    assert first.snapshot() == second.snapshot()


def test_market_master_persist_restore_roundtrip(tmp_path: Path) -> None:
    source = instruments_master.MarketMaster()
    asyncio.run(source.load_from_exchange(_MockAdapter(_load_market_specs())))

    snapshot_path = tmp_path / "market_master.parquet"
    source.persist(snapshot_path)

    restored = instruments_master.MarketMaster()
    restored.restore(snapshot_path)

    assert restored.snapshot() == source.snapshot()


def test_find_cross_venue_groups_matches_equivalent_titles() -> None:
    groups = symbology.find_cross_venue_groups(_load_market_specs())

    assert len(groups) == 1
    assert {market.venue for market in groups[0]} == {"kalshi", "limitless", "polymarket"}


def test_make_canonical_outcome_id_rejects_reserved_separator_in_components() -> None:
    with pytest.raises(ValueError, match="reserved as canonical ID separator"):
        symbology.make_canonical_outcome_id("polymarket", "mkt:1", "yes")

    with pytest.raises(ValueError, match="reserved as canonical ID separator"):
        symbology.make_canonical_outcome_id("polymarket", "mkt-1", "y:es")


def test_parse_canonical_outcome_id_rejects_extra_separator() -> None:
    with pytest.raises(ValueError, match="expected"):
        symbology.parse_canonical_outcome_id("polymarket:mkt-1:yes:extra")


def test_market_spec_rejects_duplicate_outcome_ids() -> None:
    market_payload = _load_market_specs()[0].model_dump(mode="python")
    market_payload["outcomes"] = [
        {
            "outcome_id": "YES",
            "label": "Yes",
            "canonical_id": "polymarket:us-pres-2028-winner:YES",
        },
        {
            "outcome_id": "yes",
            "label": "Duplicate yes",
            "canonical_id": "polymarket:us-pres-2028-winner:yes-dup",
        },
    ]

    with pytest.raises(ValidationError, match="duplicate `outcome_id`"):
        instrument_models.MarketSpec.model_validate(market_payload)


def test_market_spec_rejects_mismatched_canonical_outcome_id() -> None:
    market_payload = _load_market_specs()[0].model_dump(mode="python")
    market_payload["outcomes"][0]["canonical_id"] = "polymarket:wrong-market:yes"

    with pytest.raises(ValidationError, match="canonical_id"):
        instrument_models.MarketSpec.model_validate(market_payload)


# ---------------------------------------------------------------------------
# F4 Extension: outcome_group_id and simplex-group fast lookup
# ---------------------------------------------------------------------------


def _make_grouped_markets(
    group_id: str,
) -> list[instrument_models.MarketSpec]:
    """Two markets sharing the same outcome_group_id (the simplex basket)."""
    base_time = datetime(2026, 3, 1, tzinfo=UTC)
    markets = []
    for i, (market_id, outcome_id, label) in enumerate(
        [
            ("eth-hits-5k-q3", "yes", "Yes"),
            ("eth-hits-5k-q4", "yes", "Yes"),
        ]
    ):
        canonical_id = f"kalshi:{market_id}:{outcome_id}"
        markets.append(
            instrument_models.MarketSpec.model_validate(
                {
                    "market_id": market_id,
                    "venue": "kalshi",
                    "title": f"ETH > $5k — market {i + 1}",
                    "outcomes": [
                        {"outcome_id": outcome_id, "label": label, "canonical_id": canonical_id}
                    ],
                    "first_seen": base_time,
                    "last_updated": base_time,
                    "outcome_group_id": group_id,
                }
            )
        )
    return markets


def test_outcome_group_id_defaults_to_none() -> None:
    market = _load_market_specs()[0]

    assert market.outcome_group_id is None


def test_outcome_group_id_is_preserved_on_round_trip() -> None:
    markets = _make_grouped_markets("eth-5k-simplex")
    market = markets[0]

    restored = instrument_models.MarketSpec.model_validate(market.model_dump(mode="python"))

    assert restored.outcome_group_id == "eth-5k-simplex"


def test_outcome_group_id_whitespace_is_stripped_and_empty_becomes_none() -> None:
    base = _make_grouped_markets("g1")[0].model_dump(mode="python")
    base["outcome_group_id"] = "   "
    market = instrument_models.MarketSpec.model_validate(base)

    assert market.outcome_group_id is None


def test_market_master_get_markets_by_group_returns_all_members() -> None:
    master = instruments_master.MarketMaster()
    for market in _make_grouped_markets("eth-5k-simplex"):
        master.register_market(market)

    results = master.get_markets_by_group("eth-5k-simplex")

    assert len(results) == 2
    assert {m.market_id for m in results} == {"eth-hits-5k-q3", "eth-hits-5k-q4"}


def test_market_master_get_markets_by_group_returns_empty_for_unknown_group() -> None:
    master = instruments_master.MarketMaster()

    assert master.get_markets_by_group("nonexistent-group") == []


def test_market_master_get_markets_by_group_returns_defensive_copies() -> None:
    master = instruments_master.MarketMaster()
    for market in _make_grouped_markets("eth-5k-simplex"):
        master.register_market(market)

    results = master.get_markets_by_group("eth-5k-simplex")
    results[0].title = "Mutated"

    fresh = master.get_markets_by_group("eth-5k-simplex")
    assert fresh[0].title != "Mutated"


def test_market_master_group_index_cleared_when_outcome_group_id_removed() -> None:
    master = instruments_master.MarketMaster()
    market_with_group = _make_grouped_markets("eth-5k-simplex")[0]
    master.register_market(market_with_group)

    assert master.get_markets_by_group("eth-5k-simplex")

    market_without_group = market_with_group.model_copy(update={"outcome_group_id": None})
    master.register_market(market_without_group)

    assert master.get_markets_by_group("eth-5k-simplex") == []


def test_market_master_persist_restore_roundtrip_preserves_outcome_group_id(
    tmp_path: Path,
) -> None:
    source = instruments_master.MarketMaster()
    for market in _make_grouped_markets("eth-5k-simplex"):
        source.register_market(market)

    snapshot_path = tmp_path / "market_master_groups.parquet"
    source.persist(snapshot_path)

    restored = instruments_master.MarketMaster()
    restored.restore(snapshot_path)

    results = restored.get_markets_by_group("eth-5k-simplex")
    assert len(results) == 2
    assert all(m.outcome_group_id == "eth-5k-simplex" for m in results)
