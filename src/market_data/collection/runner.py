"""Run one finite durable public-book capture with an optional canonical observer."""

from __future__ import annotations

# standard library imports
import asyncio
import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# third party library imports
from websockets.exceptions import WebSocketException

# project library imports
from configuration import CaptureConfig
from market_data.books import BookProjection, CaptureReplay, NativeBook
from market_data.collection.canonical import BookCapture
from market_data.collection.receipt import ReceiptStream
from market_data.contracts import (
    BookObservation,
    CaptureRecord,
    CaptureRequest,
    FeedSocket,
    SnapshotTransport,
)
from market_data.datasets import DatasetReaders
from market_data.replay import SavedCapture
from market_data.storage import CaptureJournal
from serialization import DomainCodec
from telemetry import HealthMetric, HealthMetrics


class CaptureTransport(SnapshotTransport, Protocol):
    """Open a bounded public feed and optionally fetch its native snapshot."""

    async def open(self, timeout: float) -> FeedSocket:
        """Open the selected public feed within the remaining time budget."""
        ...


class CaptureObserver(Protocol):
    """Consume one original, already durable and reconstructed message boundary."""

    def observe(self, record: CaptureRecord, row: BookObservation) -> None:
        """Observe a canonical row after durable append and native reconstruction."""
        ...


@dataclass(frozen=True, slots=True)
class CaptureRunResult:
    """Expose the completed recording path and verified source summary to an application."""

    request: CaptureRequest
    root: Path
    summary: dict[str, object]


class CaptureRunner:
    """Own finite receipt, durable application, retry and terminal replay parity.

    The application supplies native adapters and subscription policy. The optional
    observer sees the exact same canonical boundary as the journal replay only
    after its original record has been durably acknowledged. Observer failures
    propagate and leave an inspectable interrupted journal.
    """

    def __init__(
        self,
        *,
        book_factory: Callable[[CaptureConfig], NativeBook],
        transport: CaptureTransport,
        subscriptions: Callable[[CaptureConfig], tuple[dict[str, object], ...]],
        snapshot_ready: Callable[[NativeBook], bool] | None = None,
        observer: CaptureObserver | None = None,
        health: HealthMetrics | None = None,
        snapshot_records: int | None = None,
        readers: DatasetReaders | None = None,
    ) -> None:
        """Bind source capabilities and optional bounded canonical publication.

        Args:
            book_factory: Installed native reconstruction selection.
            transport: Explicit public feed and snapshot acquisition boundary.
            subscriptions: Selected native subscribe messages per connection epoch.
            snapshot_ready: Adapter-owned predicate for a negotiated REST snapshot.
            observer: Optional synchronous, loss-intolerant canonical boundary consumer.
            health: Optional independent progress counters.
            snapshot_records: Optional 1..10000 record canonical prefix bound.
            readers: Verification readers required with snapshot_records.
        """
        if (snapshot_records is None) != (readers is None) or (
            snapshot_records is not None
            and (type(snapshot_records) is not int or not 1 <= snapshot_records <= 10_000)
        ):
            raise ValueError("book prefix requires readers and 1..10000 records")
        self._book_factory = book_factory
        self._transport = transport
        self._subscriptions = subscriptions
        self._snapshot_ready = snapshot_ready
        self._observer = observer
        self._health = health
        self._snapshot_records = snapshot_records
        self._readers = readers
        self._codec = DomainCodec()

    async def run(self, request: CaptureRequest, output: Path) -> CaptureRunResult:
        """Capture a unique request and verify its complete saved replay.

        Args:
            request: Explicit prebound recording identity; no ID is regenerated.
            output: Parent directory for this request's new recording directory.

        Returns:
            Completed exact-source summary and recording directory.

        Raises:
            ValueError: Source, callback, replay or resource admission fails.
            OSError: Persistence or transport fails outside recoverable feed loss.
        """
        request.__post_init__()
        config = request.config
        root = output / request.recording_id
        journal = CaptureJournal(root, request)
        replay = self._replay(config)
        journal.start()
        deadline, reason = time.monotonic() + config.duration_seconds, "not_started"
        for epoch in range(config.retries + 1):
            if self._health is not None:
                self._health.set(HealthMetric.RECONNECTS, epoch)
            start = CaptureRecord(kind="session", epoch=epoch, received_ns=time.time_ns())
            journal.append(start)
            outcome = replay.apply(start)
            self._observe(journal, replay, start, outcome)
            socket: FeedSocket | None = None
            reader: asyncio.Task[None] | None = None
            snapshot: asyncio.Task[None] | None = None
            queue: asyncio.Queue[CaptureRecord] = asyncio.Queue(config.queue_capacity)
            try:
                budget = deadline - time.monotonic()
                if budget <= 0:
                    reason = "duration_limit"
                    break
                try:
                    socket = await self._transport.open(budget)
                    for subscription in self._subscriptions(config):
                        async with asyncio.timeout(max(0, deadline - time.monotonic())):
                            await socket.send(self._codec.encode_json(subscription).decode())
                except OSError, WebSocketException, TimeoutError:
                    reason = "connect_failed_unknown_loss"
                else:
                    reader = asyncio.create_task(
                        ReceiptStream.frames(
                            socket,
                            queue,
                            config,
                            epoch,
                            deadline,
                            config.max_messages - replay.messages - (config.venue == "coinbase"),
                            self._health,
                        )
                    )
                    reason = "message_limit"
                    while (
                        not queue.empty()
                        or not reader.done()
                        or (snapshot is not None and not snapshot.done())
                    ):
                        record = await queue.get()
                        if record.kind == "session_end":
                            if not replay.invalid or record.reason == "overload_unknown_loss":
                                reason = record.reason
                            if record.reason in ("duration_limit", "message_limit"):
                                continue
                            record = CaptureRecord(
                                kind="gap",
                                epoch=epoch,
                                received_ns=record.received_ns,
                                reason=record.reason,
                            )
                        try:
                            await asyncio.to_thread(journal.append, record)
                        except OSError:
                            if self._health is not None:
                                self._health.set(HealthMetric.PERSISTENCE_FAILED, 1)
                            raise
                        except OverflowError:
                            reason = "storage_limit_unknown_tail"
                            break
                        if self._health is not None:
                            self._health.set(HealthMetric.PERSISTENCE, time.monotonic_ns())
                        previous_market_ns = replay.quality.last_market_ns
                        outcome = await asyncio.to_thread(replay.apply, record)
                        self._observe(journal, replay, record, outcome)
                        if self._health is not None:
                            self._health.set(HealthMetric.INVALID, len(replay.gaps))
                            if (
                                replay.quality.last_market_ns is not None
                                and replay.quality.last_market_ns != previous_market_ns
                            ):
                                age_ns = max(0, time.time_ns() - replay.quality.last_market_ns)
                                self._health.set(HealthMetric.MARKET, time.monotonic_ns() - age_ns)
                        if outcome == "invalid_frame" or record.kind == "gap":
                            if outcome == "invalid_frame":
                                reason = "invalid_stream_requires_snapshot"
                            elif reason == "message_limit":
                                reason = record.reason
                            reader.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await reader
                        if (
                            not replay.invalid
                            and self._snapshot_ready is not None
                            and self._snapshot_ready(replay.book)
                            and snapshot is None
                        ):
                            snapshot = asyncio.create_task(
                                ReceiptStream.snapshot(self._transport, queue, epoch)
                            )
            finally:
                for task in (reader, snapshot):
                    if task is not None:
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
                if socket is not None:
                    await socket.close()
            try:
                if reason not in ("duration_limit", "message_limit") and not replay.invalid:
                    gap = CaptureRecord(
                        kind="gap", epoch=epoch, received_ns=time.time_ns(), reason=reason
                    )
                    await asyncio.to_thread(journal.append, gap)
                    outcome = await asyncio.to_thread(replay.apply, gap)
                    self._observe(journal, replay, gap, outcome)
                ending = CaptureRecord(
                    kind="session_end", epoch=epoch, received_ns=time.time_ns(), reason=reason
                )
                await asyncio.to_thread(journal.append, ending)
                outcome = await asyncio.to_thread(replay.apply, ending)
                self._observe(journal, replay, ending, outcome)
            except OSError:
                if self._health is not None:
                    self._health.set(HealthMetric.PERSISTENCE_FAILED, 1)
                raise
            if reason in (
                "duration_limit",
                "message_limit",
                "storage_limit_unknown_tail",
                "overload_unknown_loss",
            ):
                break
            if epoch < config.retries and time.monotonic() < deadline:
                await asyncio.sleep(min(float(1 << epoch), max(0, deadline - time.monotonic())))
        if self._health is not None:
            self._health.set(HealthMetric.FINALIZING, 1)
        try:
            if not replay.book.ready and not replay.invalid:
                gap = CaptureRecord(
                    kind="gap",
                    epoch=replay.epoch,
                    received_ns=time.time_ns(),
                    reason="capture_ended_before_synchronization",
                )
                await self._append_terminal(journal, replay, gap)
            end = CaptureRecord(
                kind="end", epoch=replay.epoch, received_ns=time.time_ns(), reason=reason
            )
            await self._append_terminal(journal, replay, end)
        except OSError:
            if self._health is not None:
                self._health.set(HealthMetric.PERSISTENCE_FAILED, 1)
            raise
        finalization = asyncio.create_task(
            asyncio.to_thread(self._finish, journal, replay, root, request, reason)
        )
        try:
            try:
                return await asyncio.shield(finalization)
            except asyncio.CancelledError:
                await finalization
                raise
        except OSError:
            if self._health is not None:
                self._health.set(HealthMetric.PERSISTENCE_FAILED, 1)
            raise

    def _replay(self, config: CaptureConfig) -> CaptureReplay:
        """Choose full native reconstruction or the requested canonical prefix."""
        if self._snapshot_records is None:
            return CaptureReplay(config, book_factory=self._book_factory)
        if self._readers is None:
            raise ValueError("book prefix readers are unavailable")
        return BookCapture(
            config,
            self._snapshot_records,
            readers=self._readers,
            book_factory=self._book_factory,
        )

    def _observe(
        self,
        journal: CaptureJournal,
        replay: CaptureReplay,
        record: CaptureRecord,
        outcome: str,
    ) -> None:
        """Publish only durably appended canonical rows to the optional observer."""
        if self._observer is not None:
            row = BookProjection.capture(journal.count - 1, record, outcome, replay)
            self._observer.observe(record, row)

    async def _append_terminal(
        self, journal: CaptureJournal, replay: CaptureReplay, record: CaptureRecord
    ) -> None:
        """Retain a final control before publishing it to the live observer."""
        await asyncio.to_thread(journal.append, record)
        outcome = replay.apply(record)
        self._observe(journal, replay, record, outcome)

    def _finish(
        self,
        journal: CaptureJournal,
        replay: CaptureReplay,
        root: Path,
        request: CaptureRequest,
        reason: str,
    ) -> CaptureRunResult:
        """Close original bytes and independently verify whole-message parity."""
        descriptor = journal.finish(replay.started_ns or replay.finished_ns or 1)
        offline = SavedCapture.read(root, book_factory=self._book_factory)
        if isinstance(replay, BookCapture):
            replay.verify(root)
        if offline.summary() != replay.summary():
            raise ValueError("saved-input replay differs from captured message-boundary state")
        summary = {
            **offline.summary(),
            "request_identity": request.identity,
            "saved_input_identity": descriptor.sha256,
            "saved_bytes": descriptor.size_bytes,
            "capture_directory": str(root.absolute()),
            "stop_reason": reason,
            "replay_parity": True,
            "canonical_parity": isinstance(replay, BookCapture),
        }
        (root / "summary.json").write_bytes(self._codec.encode_json(summary))
        return CaptureRunResult(request=request, root=root, summary=summary)
