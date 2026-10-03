"""Run one finite durable public-book capture, or a segment chain, with optional hooks."""

from __future__ import annotations

# standard library imports
import asyncio
import contextlib
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# third party library imports
from websockets.exceptions import WebSocketException

# project library imports
from configuration import CaptureConfig, CaptureRunConfig
from market_data.books import BookProjection, CaptureReplay, NativeBook
from market_data.collection.canonical import BookCapture
from market_data.collection.receipt import CaptureQueue, ReceiptStream
from market_data.collection.segments import CaptureSegmentWriter
from market_data.contracts import (
    BookObservation,
    CaptureRecord,
    CaptureRequest,
    CaptureRunRequest,
    FeedSocket,
    SnapshotTransport,
)
from market_data.datasets import DatasetReaders
from market_data.replay import SavedCapture, SavedCaptureRun
from market_data.storage import CaptureJournal, CaptureRunJournal
from serialization import DomainCodec
from telemetry import HealthMetric, HealthMetrics, RuntimeMeasurementJournal


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


@dataclass(frozen=True, slots=True)
class CaptureChainResult:
    """Expose a completed segment-chain run directory and its verified chain summary."""

    request: CaptureRunRequest
    root: Path
    summary: dict[str, object]


# Offline chain replay is a liveness bound only; the service's stop budget is declared
# separately. It is the largest envelope SavedCaptureRun admits.
_CHAIN_VERIFICATION_SECONDS = 7200


class _Journal:
    """Append to one finite recording, exactly as a single-journal capture always has."""

    def __init__(self, journal: CaptureJournal) -> None:
        """Bind the started recording journal."""
        self.journal = journal

    @property
    def count(self) -> int:
        """Return the recording's durable record count."""
        return self.journal.count

    async def append(self, record: CaptureRecord) -> None:
        """Persist one record before any projection or application effect."""
        await asyncio.to_thread(self.journal.append, record)


class _SegmentChain:
    """Append through the collector's qualified writer, which rotates segments as storage only."""

    def __init__(
        self, writer: CaptureSegmentWriter, measurements: RuntimeMeasurementJournal | None
    ) -> None:
        """Bind the active segment writer and optional rollover timing evidence."""
        self.writer = writer
        self._measurements = measurements

    @property
    def journal(self) -> CaptureJournal:
        """Return the active segment, whose last append carries the fsync timings."""
        return self.writer.current

    @property
    def count(self) -> int:
        """Return the run-wide durable record count across every segment."""
        return self.writer.total_records

    async def append(self, record: CaptureRecord) -> None:
        """Persist one record, retaining the boundary pause whenever it sealed a segment."""
        sealed = self.writer.current
        started_ns = time.monotonic_ns()
        await self.writer.append(record)
        if self._measurements is not None and self.writer.current is not sealed:
            segment = self.writer.current.request.segment
            self._measurements.record(
                {
                    "kind": "capture_rollover",
                    "segment": None if segment is None else segment.ordinal,
                    "sealed_records": sealed.count,
                    "sealed_bytes": sealed.size,
                    "cursor": self.writer.total_records,
                    "rollover_append_ns": time.monotonic_ns() - started_ns,
                }
            )


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
        measurements: RuntimeMeasurementJournal | None = None,
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
            measurements: Optional individual monotonic timing and queue evidence.
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
        self._measurements = measurements
        self._snapshot_records = snapshot_records
        self._readers = readers
        self._codec = DomainCodec()

    async def run(
        self,
        request: CaptureRequest,
        output: Path,
        *,
        stop_requested: Callable[[], bool] | None = None,
    ) -> CaptureRunResult:
        """Capture a unique request and verify its complete saved replay.

        Args:
            request: Explicit prebound recording identity; no ID is regenerated.
            output: Parent directory for this request's new recording directory.
            stop_requested: Optional finite-service stop signal; accepted receipts drain first.

        Returns:
            Completed exact-source summary and recording directory.

        Raises:
            ValueError: Source, callback, replay or resource admission fails.
            OSError: Persistence or transport fails outside recoverable feed loss.
        """
        request.__post_init__()
        config = request.config
        root = output / request.recording_id
        journal = CaptureJournal(root, request, measure_fsync=self._measurements is not None)
        replay = self._replay(config)
        try:
            journal.start()
        except OSError, OverflowError:
            if self._health is not None:
                self._health.set(HealthMetric.PERSISTENCE_FAILED, 1)
            raise
        reason = await self._capture(
            _Journal(journal),
            replay,
            config,
            time.monotonic() + config.duration_seconds,
            config.max_messages,
            stop_requested,
        )
        return await self._finalize(
            asyncio.to_thread(self._finish, journal, replay, root, request, reason)
        )

    async def run_chain(
        self,
        request: CaptureRunRequest,
        output: Path,
        *,
        stop_requested: Callable[[], bool] | None = None,
    ) -> CaptureChainResult:
        """Capture one run through rolled-over segments and verify its exact chain replay.

        Segment limits come from the source configuration; the window bounds the whole
        run. A rollover adds no native transition, so the socket, session, sequence and
        reconstruction continue. Observer positions and measurement cursors are
        run-wide. The window's readiness instant is not used here.

        Args:
            request: Immutable source, window and implementation for a new run directory.
            output: Parent directory for the run's new directory, named by its run ID.
            stop_requested: Optional finite-service stop signal; accepted receipts drain first.

        Returns:
            Completed chain summary and run directory.

        Raises:
            ValueError: Source, callback, chain replay or resource admission fails.
            OSError: Persistence, including sealing or provisioning a segment, fails.
        """
        request.__post_init__()
        if self._snapshot_records is not None:
            raise ValueError("a segment chain does not support a canonical book prefix")
        root = output / request.run_id
        run = CaptureRunJournal(root, request, measure_fsync=self._measurements is not None)
        replay = CaptureReplay(request.config, book_factory=self._book_factory)
        try:
            try:
                run.open(resume=False)
                writer = CaptureSegmentWriter(
                    run, run.start_segment(None), previous_bytes=0, previous_records=0
                )
            except OSError, OverflowError:
                if self._health is not None:
                    self._health.set(HealthMetric.PERSISTENCE_FAILED, 1)
                raise
            stop_at_ns = CaptureRunConfig.unix_ns(request.window.stop_at)
            reason = await self._capture(
                _SegmentChain(writer, self._measurements),
                replay,
                request.config,
                time.monotonic() + max(0, (stop_at_ns - time.time_ns()) / 1e9),
                request.window.max_messages,
                stop_requested,
            )
            return await self._finalize(
                asyncio.to_thread(self._finish_chain, run, writer, replay, root, request, reason)
            )
        finally:
            run.close()

    async def _capture(
        self,
        storage: _Journal | _SegmentChain,
        replay: CaptureReplay,
        config: CaptureConfig,
        deadline: float,
        message_limit: int,
        stop_requested: Callable[[], bool] | None,
    ) -> str:
        """Receive, persist and apply every connection epoch, then retain terminal controls."""
        reason = "not_started"
        for epoch in range(config.retries + 1):
            if self._health is not None:
                self._health.set(HealthMetric.RECONNECTS, epoch)
            start = CaptureRecord(kind="session", epoch=epoch, received_ns=time.time_ns())
            try:
                await storage.append(start)
            except OverflowError:
                if self._health is not None:
                    self._health.set(HealthMetric.PERSISTENCE_FAILED, 1)
                if not isinstance(storage, _SegmentChain) or epoch == 0:
                    raise
                # A reconnect refused by the whole-run byte or segment limit opens no
                # connection; it ends the run as the frame path's storage refusal does.
                reason = "storage_limit_unknown_tail"
                gap = CaptureRecord(
                    kind="gap", epoch=replay.epoch, received_ns=time.time_ns(), reason=reason
                )
                await self._append_terminal(storage, replay, gap)
                break
            except OSError:
                if self._health is not None:
                    self._health.set(HealthMetric.PERSISTENCE_FAILED, 1)
                raise
            if self._health is not None:
                self._health.set(HealthMetric.PERSISTED_RECORDS, storage.count)
            outcome = replay.apply(start)
            self._observe(storage, replay, start, outcome)
            socket: FeedSocket | None = None
            reader: asyncio.Task[None] | None = None
            snapshot: asyncio.Task[None] | None = None
            queue = CaptureQueue(config.queue_capacity, self._health, self._measurements)
            try:
                budget = deadline - time.monotonic()
                if stop_requested is not None and stop_requested():
                    reason = "supervisor_stop"
                    break
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
                            message_limit - replay.messages - (config.venue == "coinbase"),
                            self._health,
                            stop_requested,
                        )
                    )
                    reason = "message_limit"
                    while (
                        not queue.empty()
                        or not reader.done()
                        or (snapshot is not None and not snapshot.done())
                    ):
                        record, queued_at_ns = await queue.take()
                        if record.kind == "session_end":
                            if not replay.invalid or record.reason in (
                                "overload_unknown_loss",
                                "supervisor_stop",
                            ):
                                reason = record.reason
                            if record.reason in (
                                "duration_limit",
                                "message_limit",
                                "supervisor_stop",
                            ):
                                queue.acknowledged()
                                continue
                            record = CaptureRecord(
                                kind="gap",
                                epoch=epoch,
                                received_ns=record.received_ns,
                                reason=record.reason,
                            )
                        append_started_ns = time.monotonic_ns()
                        try:
                            await storage.append(record)
                        except OSError:
                            if self._health is not None:
                                self._health.set(HealthMetric.PERSISTENCE_FAILED, 1)
                            raise
                        except OverflowError:
                            reason = "storage_limit_unknown_tail"
                            if self._health is not None:
                                self._health.set(HealthMetric.PERSISTENCE_FAILED, 1)
                            break
                        persisted_at_ns = time.monotonic_ns()
                        queue.acknowledged()
                        if self._health is not None:
                            self._health.set(HealthMetric.PERSISTENCE, persisted_at_ns)
                            self._health.set(HealthMetric.PERSISTED_RECORDS, storage.count)
                            if record.kind in ("frame", "snapshot"):
                                self._health.set(
                                    HealthMetric.RECEIPT_DURABLE_LAG_NS,
                                    max(0, persisted_at_ns - queued_at_ns),
                                )
                                self._health.set(
                                    HealthMetric.DURABLE_FRAMES,
                                    self._health.snapshot()[HealthMetric.DURABLE_FRAMES] + 1,
                                )
                        previous_market_ns = replay.quality.last_market_ns
                        outcome = await asyncio.to_thread(replay.apply, record)
                        self._observe(
                            storage,
                            replay,
                            record,
                            outcome,
                            receipt_ns=queued_at_ns,
                            append_started_ns=append_started_ns,
                            durable_ns=persisted_at_ns,
                        )
                        if self._health is not None:
                            self._health.set(HealthMetric.INVALID, replay.invalid_frames)
                            self._health.set(HealthMetric.GAPS, len(replay.gaps))
                            self._health.set(HealthMetric.DUPLICATES, replay.duplicates)
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
                if (
                    reason
                    not in (
                        "duration_limit",
                        "message_limit",
                        "supervisor_stop",
                    )
                    and not replay.invalid
                ):
                    gap = CaptureRecord(
                        kind="gap", epoch=epoch, received_ns=time.time_ns(), reason=reason
                    )
                    await storage.append(gap)
                    if self._health is not None:
                        self._health.set(HealthMetric.PERSISTED_RECORDS, storage.count)
                    outcome = await asyncio.to_thread(replay.apply, gap)
                    if self._health is not None:
                        self._health.set(HealthMetric.INVALID, replay.invalid_frames)
                        self._health.set(HealthMetric.GAPS, len(replay.gaps))
                    self._observe(storage, replay, gap, outcome)
                ending = CaptureRecord(
                    kind="session_end", epoch=epoch, received_ns=time.time_ns(), reason=reason
                )
                await storage.append(ending)
                if self._health is not None:
                    self._health.set(HealthMetric.PERSISTED_RECORDS, storage.count)
                outcome = await asyncio.to_thread(replay.apply, ending)
                if self._health is not None:
                    self._health.set(HealthMetric.INVALID, replay.invalid_frames)
                    self._health.set(HealthMetric.GAPS, len(replay.gaps))
                self._observe(storage, replay, ending, outcome)
            except OSError, OverflowError:
                if self._health is not None:
                    self._health.set(HealthMetric.PERSISTENCE_FAILED, 1)
                raise
            if reason in (
                "duration_limit",
                "message_limit",
                "supervisor_stop",
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
                await self._append_terminal(storage, replay, gap)
            end = CaptureRecord(
                kind="end", epoch=replay.epoch, received_ns=time.time_ns(), reason=reason
            )
            await self._append_terminal(storage, replay, end)
        except OSError, OverflowError:
            if self._health is not None:
                self._health.set(HealthMetric.PERSISTENCE_FAILED, 1)
            raise
        return reason

    async def _finalize[T](self, finish: Coroutine[object, object, T]) -> T:
        """Complete verification even if the caller is cancelled while it runs."""
        finalization = asyncio.create_task(finish)
        try:
            try:
                return await asyncio.shield(finalization)
            except asyncio.CancelledError:
                await finalization
                raise
        except OSError, OverflowError:
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
        storage: _Journal | _SegmentChain,
        replay: CaptureReplay,
        record: CaptureRecord,
        outcome: str,
        *,
        receipt_ns: int | None = None,
        append_started_ns: int | None = None,
        durable_ns: int | None = None,
    ) -> None:
        """Publish only durably appended canonical rows to the optional observer."""
        if self._observer is not None or self._measurements is not None:
            row = BookProjection.capture(storage.count - 1, record, outcome, replay)
            if (
                self._measurements is not None
                and record.kind in ("frame", "snapshot")
                and receipt_ns is not None
                and append_started_ns is not None
                and durable_ns is not None
            ):
                reconstructed_ns = time.monotonic_ns()
                self._measurements.record(
                    {
                        "kind": "capture_boundary",
                        "cursor": storage.count,
                        "record_kind": record.kind,
                        "outcome": row.outcome,
                        "raw_bytes": len(record.raw),
                        "receipt_ns": receipt_ns,
                        "append_started_ns": append_started_ns,
                        "durable_ns": durable_ns,
                        "reconstructed_ns": reconstructed_ns,
                        "receipt_to_durable_ns": max(0, durable_ns - receipt_ns),
                        "append_to_durable_ns": max(0, durable_ns - append_started_ns),
                        "record_fsync_ns": storage.journal.last_record_fsync_ns,
                        "cursor_checkpoint_ns": storage.journal.last_cursor_checkpoint_ns,
                        "durable_to_reconstructed_ns": max(0, reconstructed_ns - durable_ns),
                    }
                )
            if self._observer is not None:
                self._observer.observe(record, row)

    async def _append_terminal(
        self, storage: _Journal | _SegmentChain, replay: CaptureReplay, record: CaptureRecord
    ) -> None:
        """Retain a final control before publishing it to the live observer."""
        await storage.append(record)
        if self._health is not None:
            self._health.set(HealthMetric.PERSISTED_RECORDS, storage.count)
        outcome = replay.apply(record)
        if self._health is not None:
            self._health.set(HealthMetric.INVALID, replay.invalid_frames)
            self._health.set(HealthMetric.GAPS, len(replay.gaps))
        self._observe(storage, replay, record, outcome)

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

    def _finish_chain(
        self,
        run: CaptureRunJournal,
        writer: CaptureSegmentWriter,
        replay: CaptureReplay,
        root: Path,
        request: CaptureRunRequest,
        reason: str,
    ) -> CaptureChainResult:
        """Seal the last segment, retain the live summary, then replay the whole chain."""
        run.sealed(writer.current, writer.first_received_ns or replay.started_ns or 1)
        segment = writer.current.request.segment
        live = {
            **replay.summary(),
            "run_identity": request.identity,
            "stop_reason": reason,
            "saved_bytes": writer.total_bytes,
            "saved_records": writer.total_records,
            "segments": 0 if segment is None else segment.ordinal + 1,
        }
        run.finish(live)
        offline = SavedCaptureRun.read(
            root, book_factory=self._book_factory, max_seconds=_CHAIN_VERIFICATION_SECONDS
        )
        summary = {
            **live,
            **offline.summary(),
            "capture_directory": str(root.absolute()),
            "replay_parity": True,
        }
        return CaptureChainResult(request=request, root=root, summary=summary)
