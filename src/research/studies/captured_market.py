"""Reopen captured native books for an explicitly labeled receipt-clock execution scenario."""

from __future__ import annotations

# standard library imports
import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Literal

# third party library imports
from msgspec.structs import replace

# project library imports
from financial_units import DecimalGrid
from market_data.contracts import BookObservation, Level
from market_data.datasets import BookHistory, BookInput, DatasetReaders
from market_data.storage import RawStore
from research.experiments import TimeWindow
from serialization import DomainCodec
from simulation import IntentMarket


class CapturedStudyMarket:
    """Reuse verified captured OKX/Bitfinex bytes without inferring exchange-side latency.

    The required receipt-as-matching scenario uses original local knowledge
    clocks as simulated matching clocks. It is not observed exchange execution.
    Native L3 orders are explicitly aggregated into visible depth; actual queue
    ranks are not inferred. No trade prints are invented, so this source cannot
    produce passive fills. Archives with unknown receipt clocks are refused.
    """

    def __init__(
        self,
        source: BookInput,
        raw: RawStore,
        *,
        readers: DatasetReaders,
        max_bytes: int,
        clock_assumption: Literal["receipt-as-matching-v1"],
    ) -> None:
        """Bind bounded native provenance and an explicit simulation-clock assumption."""
        source.__post_init__()
        if source.capture is None or clock_assumption != "receipt-as-matching-v1":
            raise ValueError(
                "captured study market requires original receipts and explicit scenario"
            )
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("captured market requires a positive byte bound")
        if source.capture.universes is not None:
            source.capture.universes.require(source.capture.config.instrument_id, "research")
        self._source, self._raw, self._readers, self._max_bytes = source, raw, readers, max_bytes
        self._assumption = clock_assumption

    @property
    def identity(self) -> str:
        """Bind original source bytes, native configuration and the modeling interpretation."""
        return hashlib.sha256(
            DomainCodec().encode_json((self._source, self._assumption))
        ).hexdigest()

    def read(self, window: TimeWindow) -> tuple[IntentMarket, ...]:
        """Verify retained bytes and project controls/depth through the inclusive terminal cutoff.

        Original receipts round upward to the supported microsecond clock, never
        making a message available early. Full source order breaks clock ties.
        No state before the requested window is fabricated as a starting book.
        """
        window.__post_init__()
        quality = self._source.admit(self._raw, readers=self._readers, max_bytes=self._max_bytes)
        if quality.scope == "rejected" or quality.canonical is None:
            raise ValueError("captured market failed existing native source admission")
        history = DomainCodec().decode_json(quality.canonical, BookHistory)
        rows: list[IntentMarket] = []
        for row in history.observations:
            if row.received_ns is None:
                raise ValueError("captured market lacks original receipt availability")
            at = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
                microseconds=(row.received_ns + 999) // 1000
            )
            if not window.start <= at <= window.end:
                continue
            rows.append(
                IntentMarket(
                    identity=f"{self.identity}:{row.position}",
                    source_identity=self.identity,
                    instrument=str(self._source.request.config.instrument_id),
                    channel="l2",
                    source_at=at,
                    known_at=at,
                    book=self._depth(row),
                    clock_assumption=self._assumption,
                )
            )
        return tuple(rows)

    @staticmethod
    def _depth(row: BookObservation) -> BookObservation:
        """Aggregate native visible orders exactly, preserving original controls and provenance."""
        if not row.orders:
            return row
        totals: dict[tuple[str, Decimal], Fraction] = {}
        counts: dict[tuple[str, Decimal], int] = {}
        for order in row.orders:
            key = order.side, order.price
            totals[key] = totals.get(key, Fraction()) + Fraction(order.size)
            counts[key] = counts.get(key, 0) + 1
        bids = tuple(
            (price, Level(size=DecimalGrid.exact_decimal(total), order_count=counts[(side, price)]))
            for (side, price), total in sorted(totals.items())
            if side == "buy"
        )
        asks = tuple(
            (price, Level(size=DecimalGrid.exact_decimal(total), order_count=counts[(side, price)]))
            for (side, price), total in sorted(totals.items())
            if side == "sell"
        )
        return replace(
            row,
            orders=(),
            bids=bids,
            asks=asks,
            reason=(
                f"{row.reason}; visible native orders projected to L2; modeled matching at receipt"
            ),
        )
