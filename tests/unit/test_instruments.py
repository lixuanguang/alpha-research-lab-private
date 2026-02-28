"""Unit tests for instrument models, symbology, lifecycle, and market master."""

from __future__ import annotations

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

    loaded = master.load_from_exchange(_MockAdapter(markets))

    assert loaded == len(markets)
    market = master.get_market("polymarket:us-pres-2028-winner")
    assert market is not None
    assert market.title.startswith("Who will win")
    outcome = master.get_outcome("polymarket:us-pres-2028-winner:yes")
    assert outcome is not None
    assert outcome.label == "Yes"


def test_market_master_get_market_returns_defensive_copy() -> None:
    master = instruments_master.MarketMaster()
    master.load_from_exchange(_MockAdapter(_load_market_specs()))

    canonical_market_id = "polymarket:us-pres-2028-winner"
    market = master.get_market(canonical_market_id)
    assert market is not None

    market.title = "Mutated title"
    unchanged = master.get_market(canonical_market_id)

    assert unchanged is not None
    assert unchanged.title == "Who will win the 2028 US presidential election?"


def test_market_master_get_outcome_returns_defensive_copy() -> None:
    master = instruments_master.MarketMaster()
    master.load_from_exchange(_MockAdapter(_load_market_specs()))

    canonical_outcome_id = "polymarket:us-pres-2028-winner:yes"
    outcome = master.get_outcome(canonical_outcome_id)
    assert outcome is not None

    outcome.label = "Mutated label"
    unchanged = master.get_outcome(canonical_outcome_id)

    assert unchanged is not None
    assert unchanged.label == "Yes"


def test_market_master_search_returns_defensive_copies() -> None:
    master = instruments_master.MarketMaster()
    master.load_from_exchange(_MockAdapter(_load_market_specs()))

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


def test_market_master_search_filters_by_venue_category_and_lifecycle() -> None:
    master = instruments_master.MarketMaster()
    master.load_from_exchange(_MockAdapter(_load_market_specs()))

    by_venue = master.search(venue="polymarket")
    by_category = master.search(category="politics")
    by_lifecycle = master.search(lifecycle=instrument_models.MarketLifecycle.HALTED)

    assert len(by_venue) == 2
    assert len(by_category) == 2
    assert len(by_lifecycle) == 1
    assert by_lifecycle[0].market_id == "btc-above-100k-2026"


def test_market_master_search_matches_text_query() -> None:
    master = instruments_master.MarketMaster()
    master.load_from_exchange(_MockAdapter(_load_market_specs()))

    results = master.search(query="threshold")

    assert len(results) == 1
    assert results[0].category == "crypto"


def test_market_master_update_lifecycle_enforces_state_machine() -> None:
    master = instruments_master.MarketMaster()
    master.load_from_exchange(_MockAdapter(_load_market_specs()))

    canonical_market_id = "polymarket:btc-above-100k-2026"
    master.update_lifecycle(canonical_market_id, instrument_models.MarketLifecycle.RESOLVED)

    assert master.get_market(canonical_market_id) is not None
    assert (
        master.get_market(canonical_market_id).lifecycle
        == instrument_models.MarketLifecycle.RESOLVED
    )

    with pytest.raises(ValueError, match="Invalid lifecycle transition"):
        master.update_lifecycle(canonical_market_id, instrument_models.MarketLifecycle.ACTIVE)


def test_market_master_snapshot_is_deterministic() -> None:
    markets = _load_market_specs()

    first = instruments_master.MarketMaster()
    second = instruments_master.MarketMaster()
    first.load_from_exchange(_MockAdapter(markets))
    second.load_from_exchange(_MockAdapter(reversed(markets)))

    assert first.snapshot() == second.snapshot()


def test_market_master_persist_restore_roundtrip(tmp_path: Path) -> None:
    source = instruments_master.MarketMaster()
    source.load_from_exchange(_MockAdapter(_load_market_specs()))

    snapshot_path = tmp_path / "market_master.parquet"
    source.persist(snapshot_path)

    restored = instruments_master.MarketMaster()
    restored.restore(snapshot_path)

    assert restored.snapshot() == source.snapshot()


def test_find_cross_venue_groups_matches_equivalent_titles() -> None:
    groups = symbology.find_cross_venue_groups(_load_market_specs())

    assert len(groups) == 1
    assert {market.venue for market in groups[0]} == {"myriad", "polymarket"}


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
