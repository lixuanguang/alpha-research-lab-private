"""Run bounded native capture children and forward only durably reconstructed books."""

from __future__ import annotations

# standard library imports
import asyncio
from multiprocessing.connection import Connection
from multiprocessing.synchronize import Event
from pathlib import Path

# project library imports
from market_data.adapters.sources import BookAdapters
from market_data.adapters.transport import VenueSubscriptions, VenueTransport
from market_data.collection import CaptureRunner, CaptureTransport
from market_data.contracts import BookObservation, CaptureRecord, CaptureRequest
from runtime import ProcessSupervisor
from serialization import DomainCodec, WireRecord
from telemetry import HealthMetrics, RuntimeMeasurementJournal


class SourceDelivery(WireRecord, frozen=True):
    """Carry the original capture record and its durable native book projection."""

    record: CaptureRecord
    book: BookObservation

    def __post_init__(self) -> None:
        """Validate both original source envelopes at the process boundary."""
        self.record.__post_init__()
        BookObservation.__post_init__(self.book)


class _DecodedBookObservation(BookObservation, frozen=True):
    """Receive native depth whose typed decoder has validated every Level and Order.

    This private pipe schema is constructed only by strict typed decoding. Public
    consumers must invoke ``BookObservation.__post_init__`` explicitly if handed
    this row, including after unsafe mutation of one of its nested native records.
    """

    def __post_init__(self) -> None:
        """Check all remaining book invariants after nested constructor validation."""
        self._require_boundary()
        for price, _ in self.bids + self.asks:
            if not price.is_finite() or price <= 0:
                raise ValueError("book levels require positive exact prices")
        self._require_unique_state()


class _ReceivedSourceDelivery(WireRecord, frozen=True):
    """Decode the closed source pipe once, including both nested source invariants.

    Only typed decoding at the supervisor pipe boundary constructs this schema.
    The nested records run their constructor checks during decoding; repeating
    them on this envelope would rescan the same immutable native depth.
    """

    record: CaptureRecord
    book: _DecodedBookObservation


class SourceForwarder:
    """Apply bounded pipe backpressure after source persistence and before consumption."""

    def __init__(self, connection: Connection[bytes, bytes]) -> None:
        """Bind a single parent-owned receiver without sharing economic authority."""
        self.connection = connection
        self.codec = DomainCodec()

    def observe(self, record: CaptureRecord, row: BookObservation) -> None:
        """Forward exact typed bytes; a stalled pipe also stalls the child watchdog clock."""
        self.connection.send_bytes(self.codec.encode_json(SourceDelivery(record=record, book=row)))


async def capture_service(
    request: CaptureRequest,
    root: Path,
    connection: Connection[bytes, bytes],
    health: HealthMetrics,
    transport: CaptureTransport | None,
    measurement_path: Path | None = None,
    stop: Event | None = None,
) -> None:
    """Compose native source ownership, retained capture and independent process heartbeat."""
    heartbeat = asyncio.create_task(ProcessSupervisor.heartbeat(health))
    measurements: RuntimeMeasurementJournal | None = None
    try:
        if measurement_path is not None:
            measurements = RuntimeMeasurementJournal(measurement_path)
        runner = CaptureRunner(
            book_factory=BookAdapters.create,
            transport=VenueTransport(request.config) if transport is None else transport,
            subscriptions=VenueSubscriptions(),
            observer=SourceForwarder(connection),
            health=health,
            measurements=measurements,
        )
        result = await runner.run(
            request, root, stop_requested=None if stop is None else stop.is_set
        )
        (root / "source-result.json").write_bytes(DomainCodec().encode_json(result.summary))
    finally:
        try:
            if measurements is not None:
                measurements.close()
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            connection.close()


def run_source_service(
    request: CaptureRequest,
    root: Path,
    connection: Connection[bytes, bytes],
    health: HealthMetrics,
    transport: CaptureTransport | None,
    measurement_path: Path | None = None,
    stop: Event | None = None,
) -> None:
    """Own a spawned source event loop and retain a failure before process exit."""
    root.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(
            capture_service(request, root, connection, health, transport, measurement_path, stop)
        )
    except Exception as error:
        (root / "source-failure.json").write_bytes(
            DomainCodec().encode_json({"error": type(error).__name__, "reason": str(error)})
        )
        raise
