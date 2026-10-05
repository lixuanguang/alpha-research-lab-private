"""Reopen captured native books for an explicitly labeled receipt-clock execution scenario."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from market_data.books import BookDepth
from market_data.contracts import BookObservation, Level
from market_data.datasets import BookSnapshot, DatasetReaders
from market_data.storage import RawStore
from research.experiments import TimeWindow
from serialization import DomainCodec
from simulation import IntentMarket


class CapturedStudyMarket:
    """Reuse a verified published capture without inferring exchange-side latency.

    The market reads one native partition of a published book snapshot. The
    snapshot is verified against its retained raw input once, when the market is
    built; each ``read`` then streams only the requested window, so memory is
    bounded by one window, never the whole capture.

    The required receipt-as-matching scenario uses original local knowledge clocks
    as simulated matching clocks. It is not observed exchange execution. Native L3
    orders are explicitly aggregated into visible depth; actual queue ranks are not
    inferred. ``max_levels`` optionally keeps only the best levels per side, a
    declared modeling bound that is part of the market identity. No trade prints are
    invented, so this source cannot produce passive fills. Archives with unknown
    receipt clocks are refused.
    """

    def __init__(
        self,
        snapshots: Path,
        raw: RawStore,
        *,
        readers: DatasetReaders,
        snapshot_id: str,
        request_identity: str,
        max_bytes: int,
        clock_assumption: Literal["receipt-as-matching"],
        max_levels: int | None = None,
    ) -> None:
        """Verify the snapshot once and bind the partition and modeling assumptions."""
        if clock_assumption != "receipt-as-matching":
            raise ValueError("captured study market requires the explicit receipt scenario")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("captured market requires a positive byte bound")
        if max_levels is not None and (type(max_levels) is not int or max_levels <= 0):
            raise ValueError("captured market depth bound must be positive")
        self._snapshot = BookSnapshot.read(
            snapshots, raw, readers=readers, identity=snapshot_id, max_bytes=max_bytes
        )
        source = self._snapshot.selection(request_identity)
        if source.capture is None:
            raise ValueError("captured study market requires original capture receipts")
        if source.capture.universes is not None:
            source.capture.universes.require(source.capture.config.instrument_id, "research")
        self._source, self._request_identity = source, request_identity
        self._assumption, self._max_levels = clock_assumption, max_levels

    @property
    def identity(self) -> str:
        """Bind the snapshot, its native partition and every modeling interpretation."""
        return hashlib.sha256(
            DomainCodec().encode_json(
                (
                    self._snapshot.identity,
                    self._request_identity,
                    self._assumption,
                    self._max_levels,
                )
            )
        ).hexdigest()

    def read(self, window: TimeWindow) -> tuple[IntentMarket, ...]:
        """Project controls and depth for the window, streaming the verified partition.

        Original receipts round upward to the supported microsecond clock, never
        making a message available early. Full source order breaks clock ties.
        No state before the requested window is fabricated as a starting book.
        """
        window.__post_init__()
        identity = self.identity
        instrument = str(self._source.request.config.instrument_id)
        rows: list[IntentMarket] = []
        for row in self._snapshot.observations(self._request_identity):
            if row.received_ns is None:
                raise ValueError("captured market lacks original receipt availability")
            at = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
                microseconds=(row.received_ns + 999) // 1000
            )
            if at > window.end:
                break
            if at < window.start:
                continue
            rows.append(
                IntentMarket(
                    identity=f"{identity}:{row.position}",
                    source_identity=identity,
                    instrument=instrument,
                    channel="l2",
                    source_at=at,
                    known_at=at,
                    book=self._bounded(self._depth(row)),
                    clock_assumption=self._assumption,
                )
            )
        return tuple(rows)

    def _bounded(self, row: BookObservation) -> BookObservation:
        """Keep only the declared number of best levels per side, if any."""
        if self._max_levels is None:
            return row
        bids: tuple[tuple[Decimal, Level], ...] = tuple(
            sorted(row.bids, key=self._price, reverse=True)[: self._max_levels]
        )
        asks: tuple[tuple[Decimal, Level], ...] = tuple(
            sorted(row.asks, key=self._price)[: self._max_levels]
        )
        return replace(row, bids=bids, asks=asks)

    @staticmethod
    def _price(level: tuple[Decimal, Level]) -> Decimal:
        """Order levels by price."""
        return level[0]

    @staticmethod
    def _depth(row: BookObservation) -> BookObservation:
        """Aggregate native visible orders exactly, preserving original controls and provenance."""
        if not row.orders:
            return row
        return replace(
            BookDepth.project(row),
            reason=(
                f"{row.reason}; visible native orders projected to L2; modeled matching at receipt"
            ),
        )
