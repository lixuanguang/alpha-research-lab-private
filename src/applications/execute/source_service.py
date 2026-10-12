"""Run bounded native capture children and forward only durably reconstructed books."""

from __future__ import annotations

# standard library imports
import asyncio
import hashlib
import os
import time
from multiprocessing.connection import Connection
from multiprocessing.synchronize import Event
from pathlib import Path

# third party library imports
import msgspec

# project library imports
from market_data.adapters.sources import BookAdapters
from market_data.adapters.transport import VenueSubscriptions, VenueTransport
from market_data.collection import CaptureRunner, CaptureTransport
from market_data.contracts import (
    BookObservation,
    CaptureRecord,
    CaptureRequest,
    CaptureRunRequest,
    RawObject,
)
from market_data.replay import SavedCapture, SavedCaptureRun
from market_data.storage import CaptureJournal, CaptureRecording
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


class DecodedBookObservation(BookObservation, frozen=True):
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


class ReceivedSourceDelivery(WireRecord, frozen=True):
    """Decode the closed source pipe once, including both nested source invariants.

    Only typed decoding at the supervisor pipe boundary constructs this schema.
    The nested records run their constructor checks during decoding; repeating
    them on this envelope would rescan the same immutable native depth.
    """

    record: CaptureRecord
    book: DecodedBookObservation


class SourceForwarder:
    """Apply bounded pipe backpressure after source persistence and before consumption."""

    def __init__(self, connection: Connection[bytes, bytes]) -> None:
        """Bind a single parent-owned receiver without sharing economic authority."""
        self.connection = connection
        self.codec = DomainCodec()

    def observe(self, record: CaptureRecord, row: BookObservation) -> None:
        """Forward exact typed bytes; a stalled pipe also stalls the child watchdog clock."""
        self.connection.send_bytes(self.codec.encode_json(SourceDelivery(record=record, book=row)))


class SourceVerification:
    """Replay one stopped source's sealed capture and retain its explicit parity outcome.

    The source service retains ``source-result.json`` at its seal, with verification
    pending and no parity claim. Only ``verify`` writes ``source-verification.json``,
    once, bound to the sealed result's SHA-256, and only a verified record still bound
    to that result gives replay parity. ``root`` is the source's result directory, which
    holds the recording directory named by the same key.
    """

    RESULT = "source-result.json"
    RECORD = "source-verification.json"
    PENDING = "pending"

    def __init__(self, root: Path) -> None:
        """Bind one source result directory."""
        self.root = root
        self.codec = DomainCodec()

    def retain_sealed(self, summary: dict[str, object]) -> None:
        """Durably retain a sealed live summary once, with verification pending."""
        if "verification" in summary or "replay_parity" in summary:
            raise ValueError("a sealed source summary makes no verification claim")
        self._create(self.root / self.RESULT, {**summary, "verification": self.PENDING})

    def verify(self, *, max_seconds: int) -> dict[str, object]:
        """Replay the sealed capture, retain the outcome once and return it.

        Args:
            max_seconds: A chain's explicit 1..7200-second offline replay envelope. A
                single journal, bounded by its own message and byte limits, takes the
                same validated value but replays without a deadline.

        Returns:
            The retained verified record.

        Raises:
            FileExistsError: The source already has a verification record.
            ValueError: The capture is incomplete, lacks its terminal boundary, exceeds
                its limits, or differs from its sealed summary.
            TimeoutError: A chain's replay exceeds its envelope.
        """
        if type(max_seconds) is not int or not 1 <= max_seconds <= 7200:
            raise ValueError("source verification requires a finite 1..7200-second limit")
        if (self.root / self.RECORD).exists():
            raise FileExistsError("source already has a verification record")
        started = time.monotonic()
        result = (self.root / self.RESULT).read_bytes()
        try:
            record = {
                **self._replay(result, max_seconds),
                "source_result_sha256": hashlib.sha256(result).hexdigest(),
                "seconds": time.monotonic() - started,
            }
        except Exception as error:
            # Every failure is retained, so the record never reads as merely missing.
            self._create(
                self.root / self.RECORD,
                {
                    "status": "failed",
                    "source_result_sha256": hashlib.sha256(result).hexdigest(),
                    "error": f"{type(error).__name__}: {error}",
                    "seconds": time.monotonic() - started,
                },
            )
            raise
        self._create(self.root / self.RECORD, record)
        return record

    def verified(self) -> bool:
        """Report parity only for a verified record still bound to the sealed result."""
        result, record = self.root / self.RESULT, self.root / self.RECORD
        if not result.is_file() or not record.is_file():
            return False
        try:
            retained = msgspec.json.decode(record.read_bytes(), type=dict[str, object])
        except msgspec.DecodeError:
            return False
        return (
            retained.get("status") == "verified"
            and retained.get("replay_parity") is True
            and retained.get("source_result_sha256")
            == hashlib.sha256(result.read_bytes()).hexdigest()
        )

    def _replay(self, result: bytes, max_seconds: int) -> dict[str, object]:
        """Replay the saved input and compare it with every sealed summary field."""
        sealed = msgspec.json.decode(result, type=dict[str, msgspec.Raw])
        if sealed.get("verification") != msgspec.Raw(self.codec.encode_json(self.PENDING)):
            raise ValueError("source result is not a sealed capture pending verification")
        recording = CaptureRecording.read(self.root / self.root.name)
        if not recording.completed:
            raise ValueError("source capture is not sealed")
        if isinstance(recording.request, CaptureRunRequest):
            # SavedCaptureRun checks the completed chain, its terminal boundary, its
            # window limits and every field of the retained run summary.
            replay = SavedCaptureRun.read(
                recording.root, book_factory=BookAdapters.create, max_seconds=max_seconds
            )
            expected = msgspec.json.decode(
                (recording.root / "run-summary.json").read_bytes(), type=dict[str, msgspec.Raw]
            )
            kind = "chain"
        else:
            replay = SavedCapture.read(recording.root, book_factory=BookAdapters.create)
            journal = CaptureJournal(recording.root, recording.request)
            descriptor = self.codec.decode_json(
                (recording.root / "manifest.json").read_bytes(), RawObject
            )
            cursor = journal.committed_cursor()
            config = recording.request.config
            if (
                descriptor.sha256 != cursor.sha256
                or descriptor.size_bytes != cursor.offset
                or replay.messages > config.max_messages
                or descriptor.size_bytes > config.max_bytes
            ):
                raise ValueError("saved capture differs from its seal or exceeds its limits")
            expected = {
                key: msgspec.Raw(self.codec.encode_json(value))
                for key, value in {
                    **replay.summary(),
                    "request_identity": recording.identity,
                    "saved_input_identity": descriptor.sha256,
                    "saved_bytes": descriptor.size_bytes,
                }.items()
            }
            kind = "recording"
        for key, value in expected.items():
            if sealed.get(key) != value:
                raise ValueError(f"saved capture differs from the sealed source result at {key}")
        return {
            "status": "verified",
            "kind": kind,
            "identity": recording.identity,
            "key": recording.key,
            "replay_parity": True,
            "summary": replay.summary(),
        }

    def _create(self, path: Path, value: dict[str, object]) -> None:
        """Publish one complete record exclusively and durably; never replace one.

        The bytes are synchronized under a temporary name and linked into place, so a
        crash leaves either no record or a whole one.
        """
        pending = path.with_name(f".{path.name}.{os.getpid()}.pending")
        with pending.open("xb") as stream:
            stream.write(self.codec.encode_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(pending, path)
        finally:
            pending.unlink()
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


async def capture_service(
    request: CaptureRequest | CaptureRunRequest,
    root: Path,
    connection: Connection[bytes, bytes],
    health: HealthMetrics,
    transport: CaptureTransport | None,
    measurement_path: Path | None = None,
    stop: Event | None = None,
) -> None:
    """Compose native source ownership, retained capture and independent process heartbeat.

    A run request captures through rolled-over segments under ``root / run_id``; a
    single request keeps its one recording under ``root / recording_id``. The source
    seals its capture and retains the live summary with verification pending; it never
    replays the saved input, so its stop fits the supervisor's drain budget.
    """
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
        stop_requested = None if stop is None else stop.is_set
        # Stop costs only the seal; SourceVerification replays the saved input afterwards.
        if isinstance(request, CaptureRunRequest):
            sealed = await runner.seal_chain(request, root, stop_requested=stop_requested)
        else:
            sealed = await runner.seal(request, root, stop_requested=stop_requested)
        SourceVerification(root).retain_sealed(sealed.summary)
    finally:
        try:
            if measurements is not None:
                measurements.close()
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            connection.close()


def run_source_service(
    request: CaptureRequest | CaptureRunRequest,
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
