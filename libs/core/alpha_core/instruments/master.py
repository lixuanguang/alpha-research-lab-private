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
import alpha_core.utils.time as time_utils


class VenueAdapter(Protocol):
    """Protocol subset used by `MarketMaster.load_from_exchange`."""

    async def fetch_markets(self) -> list[instrument_models.MarketSpec]:
        """Return normalized venue markets."""


class MarketMaster:
    """In-memory registry of known markets and outcomes with persistence."""

    def __init__(self) -> None:
        self._markets: dict[str, instrument_models.MarketSpec] = {}
        self._outcomes: dict[str, instrument_models.OutcomeSpec] = {}
        self._market_history: dict[str, list[instrument_models.MarketSpec]] = {}
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
        earliest_first_seen = (
            market.first_seen
            if existing_market is None
            else min(existing_market.first_seen, market.first_seen)
        )
        version_market = self._normalize_market_version(
            market,
            earliest_first_seen=earliest_first_seen,
        )
        current_market = self._upsert_market_history(canonical_market_id, version_market)
        self._replace_current_market(canonical_market_id, existing_market, current_market)
        return canonical_market_id

    def get_market(self, canonical_id: str) -> instrument_models.MarketSpec | None:
        """Get a market by canonical market id (`{venue}:{market_id}`)."""
        market = self._markets.get(canonical_id)
        return None if market is None else market.model_copy(deep=True)

    def get_outcome(self, canonical_id: str) -> instrument_models.OutcomeSpec | None:
        """Get an outcome by canonical outcome id (`{venue}:{market_id}:{outcome_id}`)."""
        outcome = self._outcomes.get(canonical_id)
        return None if outcome is None else outcome.model_copy(deep=True)

    def get_market_history(self, canonical_id: str) -> list[instrument_models.MarketSpec]:
        """Return all known point-in-time versions for one market, oldest first."""
        history = self._market_history.get(canonical_id, [])
        return [market.model_copy(deep=True) for market in history]

    def market_at(
        self,
        canonical_id: str,
        as_of: datetime,
    ) -> instrument_models.MarketSpec | None:
        """Return the latest market snapshot known at *as_of*.

        When the market was already known via ``first_seen`` but the first stored
        snapshot arrived slightly later, return a conservative projection that
        does not leak future liquidity/volume values.
        """
        history = self._market_history.get(canonical_id, [])
        if not history:
            return None

        as_of_utc = time_utils.ensure_utc(as_of)
        selected: instrument_models.MarketSpec | None = None
        for market in history:
            if market.last_updated <= as_of_utc:
                selected = market
                continue
            break

        if selected is not None:
            return selected.model_copy(deep=True)

        earliest = history[0]
        if earliest.first_seen > as_of_utc:
            return None
        return _project_pre_snapshot_market(earliest, as_of_utc)

    def iter_markets_at(self, as_of: datetime) -> list[tuple[str, instrument_models.MarketSpec]]:
        """Return all markets with a point-in-time view at *as_of*, sorted by ID."""
        as_of_utc = time_utils.ensure_utc(as_of)
        markets: list[tuple[str, instrument_models.MarketSpec]] = []
        for canonical_id in sorted(self._market_history):
            market = self.market_at(canonical_id, as_of_utc)
            if market is None:
                continue
            markets.append((canonical_id, market))
        return markets

    def get_markets_by_group(self, group_id: str) -> list[instrument_models.MarketSpec]:
        """Return all markets belonging to an outcome group, sorted by canonical market id.

        Outcome groups identify sets of markets whose outcome probabilities satisfy
        the simplex constraint (``sum_i p_i = 1``), enabling cross-contract arbitrage.
        Returns an empty list when the group id is unknown.
        """
        canonical_ids = self._markets_by_group.get(group_id, [])
        return [
            market.model_copy(deep=True)
            for canonical_id in canonical_ids
            if (market := self._markets.get(canonical_id)) is not None
        ]

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
        self.register_market(updated)

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
        """Persist market history to Parquet."""
        path.parent.mkdir(parents=True, exist_ok=True)

        rows = [
            {
                "canonical_market_id": canonical_id,
                "version_ts": market.last_updated,
                "payload_json": market.model_dump_json(),
            }
            for canonical_id, versions in sorted(
                self._market_history.items(),
                key=lambda item: item[0],
            )
            for market in versions
        ]

        table = pa.Table.from_pylist(
            rows,
            schema=pa.schema(
                [
                    pa.field("canonical_market_id", pa.string(), nullable=False),
                    pa.field("version_ts", pa.timestamp("us", tz="UTC"), nullable=False),
                    pa.field("payload_json", pa.string(), nullable=False),
                ]
            ),
        )
        pq.write_table(table, path, compression="zstd")

    def restore(self, path: Path) -> None:
        """Restore registry state from Parquet history snapshot."""
        table = pq.read_table(path)
        canonical_market_ids = table.column("canonical_market_id").to_pylist()
        payloads = table.column("payload_json").to_pylist()

        self._markets.clear()
        self._outcomes.clear()
        self._market_history.clear()
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

    def _normalize_market_version(
        self,
        market: instrument_models.MarketSpec,
        *,
        earliest_first_seen: datetime,
    ) -> instrument_models.MarketSpec:
        normalized_outcomes: list[instrument_models.OutcomeSpec] = []
        for outcome in market.outcomes:
            canonical_outcome_id = symbology.make_canonical_outcome_id(
                market.venue,
                market.market_id,
                outcome.outcome_id,
            )
            normalized_outcomes.append(
                outcome.model_copy(update={"canonical_id": canonical_outcome_id})
            )

        return market.model_copy(
            deep=True,
            update={
                "venue": market.venue.lower(),
                "outcomes": normalized_outcomes,
                "first_seen": earliest_first_seen,
            },
        )

    def _upsert_market_history(
        self,
        canonical_market_id: str,
        market: instrument_models.MarketSpec,
    ) -> instrument_models.MarketSpec:
        history = self._market_history.setdefault(canonical_market_id, [])
        for index, existing in enumerate(history):
            if existing.last_updated == market.last_updated:
                history[index] = market
                break
        else:
            history.append(market)
        earliest_first_seen = min(item.first_seen for item in history)
        history = [
            item.model_copy(update={"first_seen": earliest_first_seen})
            if item.first_seen != earliest_first_seen
            else item
            for item in history
        ]
        history.sort(key=lambda item: item.last_updated)
        self._market_history[canonical_market_id] = history
        return history[-1].model_copy(deep=True)

    def _replace_current_market(
        self,
        canonical_market_id: str,
        previous_market: instrument_models.MarketSpec | None,
        current_market: instrument_models.MarketSpec,
    ) -> None:
        if previous_market is not None:
            for outcome in previous_market.outcomes:
                self._outcomes.pop(outcome.canonical_id, None)
            if previous_market.outcome_group_id is not None:
                members = self._markets_by_group.get(previous_market.outcome_group_id)
                if members is not None and canonical_market_id in members:
                    members.remove(canonical_market_id)
                    if not members:
                        del self._markets_by_group[previous_market.outcome_group_id]

        self._markets[canonical_market_id] = current_market
        for outcome in current_market.outcomes:
            self._outcomes[outcome.canonical_id] = outcome.model_copy(deep=True)
        if current_market.outcome_group_id is not None:
            group_members = self._markets_by_group.setdefault(current_market.outcome_group_id, [])
            if canonical_market_id not in group_members:
                group_members.append(canonical_market_id)
                group_members.sort()


def _matches_query(market: instrument_models.MarketSpec, query: str) -> bool:
    haystack_parts: list[str] = [market.title.lower()]
    if market.description is not None:
        haystack_parts.append(market.description.lower())
    if market.category is not None:
        haystack_parts.append(market.category.lower())
    haystack_parts.extend(tag.lower() for tag in market.tags)
    haystack_parts.extend(outcome.label.lower() for outcome in market.outcomes)
    return query in " ".join(haystack_parts)


def _project_pre_snapshot_market(
    market: instrument_models.MarketSpec,
    as_of: datetime,
) -> instrument_models.MarketSpec:
    lifecycle = instrument_models.MarketLifecycle.ACTIVE
    if market.resolution_date is not None and market.resolution_date <= as_of:
        lifecycle = instrument_models.MarketLifecycle.RESOLVED
    return market.model_copy(
        deep=True,
        update={
            "last_updated": market.first_seen,
            "lifecycle": lifecycle,
            "volume": None,
            "liquidity": None,
        },
    )
