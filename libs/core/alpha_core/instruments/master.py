"""In-memory market master registry with persistence support."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

import alpha_core.instruments.lifecycle as lifecycle_utils
import alpha_core.instruments.models as instrument_models
import alpha_core.instruments.symbology as symbology


class VenueAdapter(Protocol):
    """Protocol subset used by `MarketMaster.load_from_exchange`."""

    async def fetch_markets(self) -> list[instrument_models.MarketSpec]:
        """Return normalized venue markets."""


class MarketMaster:
    """In-memory registry of known markets and outcomes with persistence."""

    def __init__(self) -> None:
        self._markets: dict[str, instrument_models.MarketSpec] = {}
        self._outcomes: dict[str, instrument_models.OutcomeSpec] = {}
        # Maps outcome_group_id → sorted list of canonical market IDs for fast
        # simplex-constrained basket lookup.
        self._markets_by_group: dict[str, list[str]] = {}

    async def load_from_exchange(self, adapter: VenueAdapter) -> int:
        """Fetch and register all markets from an exchange adapter."""
        markets = await adapter.fetch_markets()

        for index, market in enumerate(markets):
            if not isinstance(market, instrument_models.MarketSpec):
                raise TypeError(
                    "`fetch_markets()` returned non-MarketSpec item at "
                    f"index {index}: {type(market).__name__}"
                )
            self.register_market(market)

        return len(markets)

    def register_market(self, market: instrument_models.MarketSpec) -> str:
        """Register a market and all outcomes, returning canonical market id."""
        canonical_market_id = symbology.make_canonical_market_id(market.venue, market.market_id)
        existing_market = self._markets.get(canonical_market_id)
        if existing_market is not None:
            for existing_outcome in existing_market.outcomes:
                existing_canonical_id = symbology.make_canonical_outcome_id(
                    existing_market.venue,
                    existing_market.market_id,
                    existing_outcome.outcome_id,
                )
                self._outcomes.pop(existing_canonical_id, None)
            # Remove from old group index if group membership may have changed.
            if existing_market.outcome_group_id is not None:
                _remove_from_group(
                    self._markets_by_group, existing_market.outcome_group_id, canonical_market_id
                )

        stored_market = market.model_copy(deep=True)
        first_seen = (
            stored_market.first_seen
            if existing_market is None
            else min(existing_market.first_seen, stored_market.first_seen)
        )
        last_updated = (
            stored_market.last_updated
            if existing_market is None
            else max(existing_market.last_updated, stored_market.last_updated)
        )
        normalized_outcomes: list[instrument_models.OutcomeSpec] = []

        for outcome in stored_market.outcomes:
            canonical_outcome_id = symbology.make_canonical_outcome_id(
                stored_market.venue,
                stored_market.market_id,
                outcome.outcome_id,
            )
            normalized_outcome = outcome.model_copy(update={"canonical_id": canonical_outcome_id})
            normalized_outcomes.append(normalized_outcome)
            self._outcomes[canonical_outcome_id] = normalized_outcome

        new_group_id = stored_market.outcome_group_id
        self._markets[canonical_market_id] = stored_market.model_copy(
            update={
                "venue": stored_market.venue.lower(),
                "outcomes": normalized_outcomes,
                "first_seen": first_seen,
                "last_updated": last_updated,
            }
        )
        if new_group_id is not None:
            group_members = self._markets_by_group.setdefault(new_group_id, [])
            if canonical_market_id not in group_members:
                group_members.append(canonical_market_id)
                group_members.sort()
        return canonical_market_id

    def get_market(self, canonical_id: str) -> instrument_models.MarketSpec | None:
        """Get a market by canonical market id (`{venue}:{market_id}`)."""
        market = self._markets.get(canonical_id)
        if market is None:
            return None
        return market.model_copy(deep=True)

    def get_outcome(self, canonical_id: str) -> instrument_models.OutcomeSpec | None:
        """Get an outcome by canonical outcome id (`{venue}:{market_id}:{outcome_id}`)."""
        outcome = self._outcomes.get(canonical_id)
        if outcome is None:
            return None
        return outcome.model_copy(deep=True)

    def get_markets_by_group(self, group_id: str) -> list[instrument_models.MarketSpec]:
        """Return all markets belonging to an outcome group, sorted by canonical market id.

        Outcome groups identify sets of markets whose outcome probabilities satisfy
        the simplex constraint (``sum_i p_i = 1``), enabling cross-contract arbitrage.
        Returns an empty list when the group id is unknown.
        """
        canonical_ids = self._markets_by_group.get(group_id, [])
        markets: list[instrument_models.MarketSpec] = []
        for canonical_id in canonical_ids:
            market = self._markets.get(canonical_id)
            if market is not None:
                markets.append(market.model_copy(deep=True))
        return markets

    def search(
        self,
        query: str = "",
        venue: str | None = None,
        category: str | None = None,
        lifecycle: instrument_models.MarketLifecycle | None = None,
    ) -> list[instrument_models.MarketSpec]:
        """Search markets by text and optional filters."""
        normalized_query = query.strip().lower()
        normalized_venue = venue.strip().lower() if venue is not None else None
        normalized_category = category.strip().lower() if category is not None else None

        results: list[instrument_models.MarketSpec] = []
        for market in self._markets.values():
            if normalized_venue is not None and market.venue != normalized_venue:
                continue

            market_category = market.category.lower() if market.category is not None else None
            if normalized_category is not None and market_category != normalized_category:
                continue

            if lifecycle is not None and market.lifecycle != lifecycle:
                continue

            if normalized_query and not _matches_query(market, normalized_query):
                continue

            results.append(market)

        sorted_results = sorted(results, key=lambda market: (market.venue, market.market_id))
        return [market.model_copy(deep=True) for market in sorted_results]

    def update_lifecycle(
        self,
        canonical_id: str,
        new_state: instrument_models.MarketLifecycle,
    ) -> None:
        """Transition market lifecycle after validating transition rules."""
        current = self._markets.get(canonical_id)
        if current is None:
            raise KeyError(f"Unknown market canonical id: {canonical_id}")

        lifecycle_utils.validate_transition(current.lifecycle, new_state)
        updated = current.model_copy(
            update={
                "lifecycle": new_state,
                "last_updated": datetime.now(tz=UTC),
            }
        )
        self._markets[canonical_id] = updated

    def snapshot(self) -> dict[str, object]:
        """Return deterministic registry snapshot for reproducibility."""
        market_items = sorted(self._markets.items(), key=lambda item: item[0])
        outcome_items = sorted(self._outcomes.items(), key=lambda item: item[0])

        return {
            "market_count": len(market_items),
            "outcome_count": len(outcome_items),
            "markets": {
                canonical_id: market.model_dump(mode="json")
                for canonical_id, market in market_items
            },
            "outcomes": {
                canonical_id: outcome.model_dump(mode="json")
                for canonical_id, outcome in outcome_items
            },
        }

    def persist(self, path: Path) -> None:
        """Persist current market registry to Parquet."""
        path.parent.mkdir(parents=True, exist_ok=True)

        rows = [
            {
                "canonical_market_id": canonical_id,
                "payload_json": market.model_dump_json(),
            }
            for canonical_id, market in sorted(self._markets.items(), key=lambda item: item[0])
        ]

        table = pa.Table.from_pylist(
            rows,
            schema=pa.schema(
                [
                    pa.field("canonical_market_id", pa.string(), nullable=False),
                    pa.field("payload_json", pa.string(), nullable=False),
                ]
            ),
        )
        pq.write_table(table, path, compression="zstd")

    def restore(self, path: Path) -> None:
        """Restore registry state from Parquet snapshot."""
        table = pq.read_table(path)
        canonical_market_ids = table.column("canonical_market_id").to_pylist()
        payloads = table.column("payload_json").to_pylist()

        self._markets.clear()
        self._outcomes.clear()
        self._markets_by_group.clear()

        for canonical_market_id, payload_json in zip(canonical_market_ids, payloads, strict=True):
            if not isinstance(canonical_market_id, str):
                raise TypeError("Invalid canonical market id in persisted snapshot")
            if not isinstance(payload_json, str):
                raise TypeError("Invalid payload in persisted snapshot")

            market = instrument_models.MarketSpec.model_validate_json(payload_json)
            registered_market_id = self.register_market(market)
            if registered_market_id != canonical_market_id:
                raise ValueError(
                    "Persisted canonical market id does not match normalized market payload: "
                    f"{canonical_market_id} != {registered_market_id}"
                )


def _matches_query(market: instrument_models.MarketSpec, query: str) -> bool:
    haystack_parts: list[str] = [market.title.lower()]
    if market.description is not None:
        haystack_parts.append(market.description.lower())
    if market.category is not None:
        haystack_parts.append(market.category.lower())
    haystack_parts.extend(tag.lower() for tag in market.tags)
    haystack_parts.extend(outcome.label.lower() for outcome in market.outcomes)
    return query in " ".join(haystack_parts)


def _remove_from_group(
    index: dict[str, list[str]], group_id: str, canonical_market_id: str
) -> None:
    """Remove a canonical market id from a group index entry, pruning empty entries."""
    members = index.get(group_id)
    if members is None:
        return
    try:
        members.remove(canonical_market_id)
    except ValueError:
        pass
    if not members:
        del index[group_id]
