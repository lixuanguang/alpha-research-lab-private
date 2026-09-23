"""Select and replay locally known public trades without backdating archive availability."""

from __future__ import annotations

# standard library imports
import hashlib
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Literal

# project library imports
from configuration import UniverseSelection
from market_data.contracts import RequestBinding
from market_data.datasets import (
    DatasetReaders,
    PublicTradeHistory,
    PublicTradeManifest,
    PublicTradeObservation,
    SnapshotStore,
)
from market_data.storage import RawStore
from reference_data.catalogs import InstrumentDefinition, ReferenceHistory
from reference_data.instruments import InstrumentId
from serialization import DomainCodec, WireRecord


class PublicTradeQuery(WireRecord, frozen=True, kw_only=True):
    """Pin a saved input, half-open event interval, inclusive cutoff and independent purpose."""

    snapshot_id: str
    instruments: tuple[InstrumentId, ...]
    start: datetime
    end: datetime
    known_at: datetime
    max_bytes: int
    purpose: Literal["research", "strategy"] = "research"

    def __post_init__(self) -> None:
        """Reject malformed selections before opening source or snapshot bytes."""
        RequestBinding(self.snapshot_id)
        UniverseSelection(
            collection=(), research=self.instruments, strategy=(), authorized_trading=()
        )
        for name, instant in (
            ("start", self.start),
            ("end", self.end),
            ("known_at", self.known_at),
        ):
            self._require_utc(instant, field_name=name)
        if (
            not self.instruments
            or self.start >= self.end
            or type(self.max_bytes) is not int
            or self.max_bytes <= 0
            or self.purpose not in ("research", "strategy")
        ):
            raise ValueError("invalid public trade query")

    @property
    def identity(self) -> str:
        """Pin semantic selection independently of resource budgets and file locations."""
        self.__post_init__()
        return hashlib.sha256(
            DomainCodec().encode_json(
                (
                    "public-trade-query-v1",
                    self.snapshot_id,
                    self.instruments,
                    self.start,
                    self.end,
                    self.known_at,
                    self.purpose,
                )
            )
        ).hexdigest()


class PublicTradeResult(WireRecord, frozen=True, kw_only=True):
    """Retain selected values, units, reference history, duplicate counts and limitations."""

    query: PublicTradeQuery
    instruments: tuple[InstrumentDefinition, ...]
    rows: tuple[PublicTradeObservation, ...]
    references: ReferenceHistory
    duplicate_observations: int
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require typed results whose data and reference assertions obey the cutoff."""
        self.query.__post_init__()
        self.references.__post_init__()
        if any(s.ts_knowledge > self.query.known_at for s in self.references.specifications):
            raise ValueError("reference result includes future knowledge")
        if (
            type(self.rows) is not tuple
            or type(self.instruments) is not tuple
            or type(self.reasons) is not tuple
            or type(self.duplicate_observations) is not int
            or self.duplicate_observations < 0
        ):
            raise ValueError("invalid public query result")
        for row in self.rows:
            row.__post_init__()
            if (
                row.ts_knowledge > self.query.known_at
                or not self.query.start <= row.ts_event < self.query.end
                or row.receipt.request.instrument.instrument_id not in self.query.instruments
            ):
                raise ValueError("public result violates its selection")


class PublicReplayCursor(WireRecord, frozen=True, kw_only=True):
    """Bind a completed public response prefix to an immutable query selection."""

    query_identity: str
    index: int

    def __post_init__(self) -> None:
        """Reject foreign identities and invalid prefix positions."""
        RequestBinding(self.query_identity)
        if type(self.index) is not int or self.index < 0:
            raise ValueError("invalid public replay cursor")


class PublicTradeReader:
    """Reopen fully verified snapshots and select economic versions at local knowledge cutoffs."""

    def __init__(self, snapshots: Path, raw: RawStore, *, readers: DatasetReaders) -> None:
        """Bind the existing snapshot store and explicitly installed source capabilities."""
        self._snapshots, self._raw, self._readers = snapshots, raw, readers

    def read(self, query: PublicTradeQuery) -> PublicTradeResult:
        """Resolve the last changed version known by the cutoff before event-window filtering.

        Repeated equal observations preserve their earliest local knowledge. Later
        source changes create observable revisions; they never rewrite earlier reads.
        No source completeness, original availability or empirical quality is inferred.
        """
        history, instruments = self._open(query)
        versions: dict[tuple[InstrumentId, str], PublicTradeObservation] = {}
        duplicates = 0
        for row in history.observations:
            instrument = row.receipt.request.instrument.instrument_id
            if instrument not in query.instruments or row.ts_knowledge > query.known_at:
                continue
            key = instrument, row.trade.trade_id
            previous = versions.get(key)
            if previous is not None and previous.trade == row.trade:
                duplicates += query.start <= row.ts_event < query.end
            else:
                versions[key] = row
        rows = tuple(
            sorted(
                (row for row in versions.values() if query.start <= row.ts_event < query.end),
                key=self._order,
            )
        )
        reasons = [
            "original historical availability unknown; cutoff uses local durable receipt",
            "venue completeness and exhaustive revisions unproven; polling can miss trades",
        ]
        if not rows:
            reasons.append("no selected observations; empty does not prove a quiet market")
        if any(row.specification_identity is None for row in rows):
            reasons.append("specification valid and known for some observations is unknown")
        return PublicTradeResult(
            query=query,
            instruments=instruments,
            rows=rows,
            references=ReferenceHistory(
                specifications=tuple(
                    s
                    for s in history.references.specifications
                    if s.ts_knowledge <= query.known_at
                    and s.instrument.instrument_id in query.instruments
                )
            ),
            duplicate_observations=duplicates,
            reasons=tuple(reasons),
        )

    def replay(
        self, query: PublicTradeQuery, *, after: PublicReplayCursor | None = None
    ) -> Iterator[tuple[PublicReplayCursor, PublicTradeObservation]]:
        """Replay all observed versions in local knowledge order with an explicit prefix cursor.

        Persist query.identity and the returned next index with consumer state. A
        changed query must not reuse that cursor. Repeated identical observations are
        retained here for source replay and deduplicated only by cutoff reads.
        """
        history, _ = self._open(query)
        selected_ids = {
            (row.receipt.request.instrument.instrument_id, row.trade.trade_id)
            for row in history.observations
            if query.start <= row.ts_event < query.end and row.ts_knowledge <= query.known_at
        }
        rows = tuple(
            sorted(
                (
                    r
                    for r in history.observations
                    if r.receipt.request.instrument.instrument_id in query.instruments
                    and (r.receipt.request.instrument.instrument_id, r.trade.trade_id)
                    in selected_ids
                    and r.ts_knowledge <= query.known_at
                ),
                key=self._order,
            )
        )
        if after is not None:
            after.__post_init__()
            if after.query_identity != query.identity:
                raise ValueError("public replay cursor belongs to another query")
        index_after = 0 if after is None else after.index
        if not 0 <= index_after <= len(rows):
            raise ValueError("public replay cursor outside verified input")
        for index in range(index_after, len(rows)):
            yield PublicReplayCursor(query_identity=query.identity, index=index + 1), rows[index]

    def _open(
        self, query: PublicTradeQuery
    ) -> tuple[PublicTradeHistory, tuple[InstrumentDefinition, ...]]:
        """Admit complete snapshot bytes and enforce selected universe before returning rows."""
        query.__post_init__()
        manifest = SnapshotStore(
            self._snapshots, self._raw, readers=self._readers, manifest_type=PublicTradeManifest
        ).read(query.snapshot_id, max_bytes=query.max_bytes)
        partition = manifest.partitions[0]
        job = partition.acquisition.job
        for instrument in query.instruments:
            job.universes.require(instrument, query.purpose)
            job.universes.require(instrument, "collection")
        if query.start < job.start or query.end > job.end:
            raise ValueError("query extends outside saved event selection")
        with (self._snapshots / query.snapshot_id / partition.sha256).open("rb") as source:
            payload = source.read(query.max_bytes + 1)
        if (
            len(payload) != partition.size_bytes
            or hashlib.sha256(payload).hexdigest() != partition.sha256
        ):
            raise ValueError("public history changed after admission")
        return DomainCodec().decode_json(payload, PublicTradeHistory), tuple(
            i for i in job.instruments if i.instrument_id in query.instruments
        )

    @staticmethod
    def _order(row: PublicTradeObservation) -> tuple[datetime, str, int, int]:
        """Order equal-knowledge inputs by canonical listing and retained source position."""
        return (
            row.ts_knowledge,
            str(row.receipt.request.instrument.instrument_id),
            row.receipt.request.ordinal,
            row.position,
        )
