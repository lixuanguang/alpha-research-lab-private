"""Run bounded native capture children and forward only durably reconstructed books."""

from __future__ import annotations

# standard library imports
import asyncio
from multiprocessing.connection import Connection
from pathlib import Path

# project library imports
from market_data.adapters.sources import BookAdapters
from market_data.adapters.transport import VenueSubscriptions, VenueTransport
from market_data.collection import CaptureRunner, CaptureTransport
from market_data.contracts import BookObservation, CaptureRecord, CaptureRequest
from runtime import ProcessSupervisor
from serialization import DomainCodec, WireRecord
from telemetry import HealthMetrics


class SourceDelivery(WireRecord, frozen=True):
    """Carry the original capture record and its durable native book projection."""

    record: CaptureRecord
    book: BookObservation

    def __post_init__(self) -> None:
        """Validate both original source envelopes at the process boundary."""
        self.record.__post_init__()
        self.book.__post_init__()


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
) -> None:
    """Compose native source ownership, retained capture and independent process heartbeat."""
    heartbeat = asyncio.create_task(ProcessSupervisor.heartbeat(health))
    try:
        runner = CaptureRunner(
            book_factory=BookAdapters.create,
            transport=VenueTransport(request.config) if transport is None else transport,
            subscriptions=VenueSubscriptions(),
            observer=SourceForwarder(connection),
            health=health,
        )
        result = await runner.run(request, root)
        (root / "source-result.json").write_bytes(DomainCodec().encode_json(result.summary))
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
) -> None:
    """Own a spawned source event loop and retain a failure before process exit."""
    root.mkdir(parents=True, exist_ok=True)
    try:
        asyncio.run(capture_service(request, root, connection, health, transport))
    except Exception as error:
        (root / "source-failure.json").write_bytes(
            DomainCodec().encode_json({"error": type(error).__name__, "reason": str(error)})
        )
        raise
