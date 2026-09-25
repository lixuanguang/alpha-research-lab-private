"""Deliver canonical live books and UTC cadence ticks to a paper candidate."""

from __future__ import annotations

# standard library imports
import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

# project library imports
from execution import PaperMarket
from financial_units import Price, Quantity
from market_data.contracts import BookObservation, CaptureRecord
from research.observations import LiveBookDecisionSource
from runtime.paper import PaperCandidateRuntime
from serialization import DomainCodec, WireRecord


class LiveBookDelivery(WireRecord, frozen=True):
    """Retain raw receipt, reconstruction and separately observed local delivery time."""

    record: CaptureRecord
    book: BookObservation
    available_at: datetime

    def __post_init__(self) -> None:
        """Reject invented availability before the original received frame."""
        self.record.__post_init__()
        self.book.__post_init__()
        self._require_utc(self.available_at, field_name="live delivery")
        received = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
            microseconds=(self.record.received_ns + 999) // 1000
        )
        if self.available_at < received:
            raise ValueError("live delivery precedes receipt")


class PaperCaptureObserver:
    """Bind durably captured native books to the same candidate used by replay.

    The collector calls ``observe`` only after append/fsync and reconstruction.
    Delivery records are kept in the existing OMS journal. Replaying ``deliver``
    with those records preserves the actual knowledge clock instead of replacing
    it with download time or the later replay wall clock.
    """

    def __init__(self, source: LiveBookDecisionSource, runtime: PaperCandidateRuntime) -> None:
        """Bind one admitted live source and its already open dedicated runtime."""
        self.source, self.runtime = source, runtime
        self._codec = DomainCodec()

    def observe(self, record: CaptureRecord, row: BookObservation) -> None:
        """Observe actual post-persistence delivery independently of original receipt."""
        self.deliver(LiveBookDelivery(record=record, book=row, available_at=datetime.now(UTC)))

    def deliver(self, delivery: LiveBookDelivery) -> None:
        """Replay or deliver one exact retained envelope before exposing a priced market."""
        delivery.__post_init__()
        payload = self._codec.encode_json(delivery)
        identity = hashlib.sha256(payload).hexdigest()
        self.runtime.input_delivery(identity=identity, at=delivery.available_at, payload=payload)
        self.source.accept(delivery.record, delivery.book, available_at=delivery.available_at)
        if delivery.book.outcome not in ("snapshot", "update"):
            return
        quote = self.source.current_quote(
            self.runtime.loaded.deployment.entity, delivery.available_at
        )
        if quote is None or quote.market_state != "two_sided":
            return
        bid, ask = quote.bid, quote.ask
        if bid is None or ask is None:
            return
        dimension, currency = (
            self.runtime.config.maximum.dimension,
            self.runtime.config.tick.currency,
        )
        self.runtime.market(
            PaperMarket(
                identity=identity,
                at=delivery.available_at,
                bid=Price(value=bid.price, currency=currency, per=dimension),
                ask=Price(value=ask.price, currency=currency, per=dimension),
                bid_quantity=Quantity(value=bid.quantity, dimension=dimension),
                ask_quantity=Quantity(value=ask.quantity, dimension=dimension),
            )
        )

    async def timers(self, stop: asyncio.Event) -> None:
        """Drive actual UTC cadence while preventing delayed ticks from preceding delivered data.

        The monotonic event loop bounds elapsed waits. Missed UTC ticks remain
        gaps and use the candidate's declared pause/reset policy. A wall-clock
        regression fails visibly; this method never repairs source timestamps.
        """
        cadence = timedelta(microseconds=self.runtime.loaded.manifest.cadence_us)
        starts = self.runtime.loaded.deployment.starts_at
        previous_now = datetime.now(UTC)
        at = starts
        while not stop.is_set():
            now = datetime.now(UTC)
            if now < previous_now:
                raise ValueError("paper scheduler UTC clock regressed")
            previous_now = now
            minimum = max(now, self.runtime.checkpoint().last_at)
            if at < minimum:
                ticks = (minimum - starts) // cadence
                at = starts + ticks * cadence
                if at < minimum:
                    at += cadence
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(0, (at - now).total_seconds()))
                return
            except TimeoutError:
                if self.runtime.checkpoint().last_at <= at:
                    self.runtime.timer(identity=at.isoformat(), at=at)
                at += cadence
