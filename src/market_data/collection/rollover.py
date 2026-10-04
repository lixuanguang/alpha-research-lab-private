"""Collect a fixed public UTC window through one gap-aware native segment chain."""

from __future__ import annotations

# standard library imports
import asyncio
import contextlib
import time
from collections.abc import Callable
from pathlib import Path

# third party library imports
from websockets.exceptions import WebSocketException

# project library imports
from configuration import CaptureConfig, CaptureRunConfig
from market_data.books import CaptureReplay, NativeBook
from market_data.collection.receipt import CaptureQueue, ReceiptStream
from market_data.collection.runner import CaptureTransport
from market_data.collection.segments import CaptureSegmentWriter
from market_data.contracts import CaptureRecord, CaptureRunRequest, FeedSocket
from market_data.storage import CaptureRunJournal
from serialization import DomainCodec


class CaptureRunStop:
    """Keep user stop, startup readiness and the absolute source deadline explicit."""

    def __init__(
        self,
        root: Path,
        *,
        ready_by_ns: int,
        stop_at_ns: int,
        initial_ready_ns: int | None,
        stop_requested: Callable[[], bool] | None,
    ) -> None:
        """Bind this invocation's stop capability and previously observed startup readiness."""
        self.root, self.ready_by_ns, self.stop_at_ns = root, ready_by_ns, stop_at_ns
        self.ready_ns = initial_ready_ns
        self.last_ready_ns: int | None = None
        self._stop_requested = stop_requested

    def requested(self) -> bool:
        """Stop for an explicit request, missed initial synchronization or the fixed UTC end."""
        return (
            self._user_stop()
            or time.time_ns() >= self.stop_at_ns
            or (self.ready_ns is None and time.time_ns() >= self.ready_by_ns)
        )

    @property
    def reason(self) -> str:
        """Expose the fixed stop cause without treating a readiness failure as coverage."""
        if self._user_stop():
            return "supervisor_stop"
        return "stop_deadline" if time.time_ns() >= self.stop_at_ns else "readiness_deadline"

    def _user_stop(self) -> bool:
        """Combine a durable public stop marker with the caller's cooperative signal."""
        return (self.root / "stop-requested").exists() or (
            self._stop_requested is not None and self._stop_requested()
        )


class CaptureRunRunner:
    """Preserve one socket/parser across rollover and gap every reconnect or explicit resume."""

    def __init__(
        self,
        *,
        book_factory: Callable[[CaptureConfig], NativeBook],
        transport: CaptureTransport,
        subscriptions: Callable[[CaptureConfig], tuple[dict[str, object], ...]],
    ) -> None:
        """Bind existing native reconstruction and public transport capabilities."""
        self._book_factory = book_factory
        self._transport = transport
        self._subscriptions = subscriptions
        self._codec = DomainCodec()

    async def run(
        self,
        request: CaptureRunRequest,
        root: Path,
        *,
        resume: bool = False,
        stop_requested: Callable[[], bool] | None = None,
    ) -> dict[str, object]:
        """Collect the fixed source window; retain full independent replay as a separate command.

        Args:
            request: Immutable source, implementation, UTC window and resource selection.
            root: New owned run directory, or the exact prior directory for explicit resume.
            resume: Verify prior cursors and retain an interruption gap before a fresh session.
            stop_requested: Optional cooperative signal; accepted receipts drain before sealing.

        Returns:
            Live-state identity, bounded counts, observed readiness and retained gap evidence.

        Raises:
            ValueError: Requests, source reconstruction or durable identities conflict.
            OSError: Persistence or exclusive ownership cannot be established.
        """
        run = CaptureRunJournal(root, request)
        journals = run.open(resume=resume)
        try:
            if (root / "run-summary.json").exists():
                raise ValueError("completed capture run cannot resume; verify the saved run")
            replay = CaptureReplay(request.config, book_factory=self._book_factory)
            total_bytes = total_records = tail_bytes = 0
            interrupted = False
            for journal in journals:
                cursor = journal.committed_cursor()
                tail_bytes += max(
                    0, (journal.root / "journal.jsonl").stat().st_size - cursor.offset
                )
                if not (journal.root / "manifest.json").exists():
                    await asyncio.to_thread(journal.seal_interrupted)
                    interrupted = True
                for record in journal.records(completed=True):
                    replay.apply(record)
                    total_records += 1
                total_bytes += cursor.offset
            if replay.ended:
                raise ValueError("capture run ended before its final summary; verify the saved run")
            stop = CaptureRunStop(
                root,
                ready_by_ns=CaptureRunConfig.unix_ns(request.window.ready_by),
                stop_at_ns=CaptureRunConfig.unix_ns(request.window.stop_at),
                initial_ready_ns=run.initial_ready_ns(),
                stop_requested=stop_requested,
            )
            start_ns = CaptureRunConfig.unix_ns(request.window.start_at)
            if not journals:
                while time.time_ns() < start_ns:
                    if stop.requested():
                        run.progress(status="stopped_before_start", stop_reason=stop.reason)
                        return {"run_identity": request.identity, "stop_reason": stop.reason}
                    run.progress(status="waiting_start", expected_completion=request.window.stop_at)
                    await asyncio.sleep(min(1.0, max(0, (start_ns - time.time_ns()) / 1e9)))
            current = await asyncio.to_thread(run.start_segment, journals[-1] if journals else None)
            writer = CaptureSegmentWriter(
                run, current, previous_bytes=total_bytes, previous_records=total_records
            )
            if journals:
                if replay.epoch < 0:
                    await self._append(
                        writer,
                        replay,
                        CaptureRecord(kind="session", epoch=0, received_ns=time.time_ns()),
                    )
                await self._append(
                    writer,
                    replay,
                    CaptureRecord(
                        kind="gap",
                        epoch=replay.epoch,
                        received_ns=time.time_ns(),
                        reason="interrupted_persistence_unknown_tail"
                        if interrupted
                        else "resume_unknown_loss",
                    ),
                )
            deadline = time.monotonic() + max(0, (stop.stop_at_ns - time.time_ns()) / 1e9)
            reason = "reconnect_limit"
            for epoch in range(replay.epoch + 1, request.window.max_reconnects + 1):
                if time.monotonic() >= deadline or stop.requested():
                    reason = "stop_deadline" if time.monotonic() >= deadline else stop.reason
                    break
                try:
                    await self._append(
                        writer,
                        replay,
                        CaptureRecord(kind="session", epoch=epoch, received_ns=time.time_ns()),
                    )
                except OverflowError as error:
                    reason = self._limit_reason(error)
                    break
                reason = await self._session(writer, replay, stop, epoch, deadline)
                if reason in (
                    "duration_limit",
                    "message_limit",
                    "supervisor_stop",
                    "stop_deadline",
                    "readiness_deadline",
                    "run_byte_limit_unknown_tail",
                    "run_segment_limit_unknown_tail",
                    "overload_unknown_loss",
                    "frame_limit_unknown_loss",
                ):
                    break
                if epoch < request.window.max_reconnects:
                    await asyncio.sleep(
                        min(float(1 << min(epoch, 4)), max(0, deadline - time.monotonic()))
                    )
            if replay.epoch < 0:
                await self._append(
                    writer,
                    replay,
                    CaptureRecord(kind="session", epoch=0, received_ns=time.time_ns()),
                )
            if reason not in ("stop_deadline", "duration_limit") or not replay.book.ready:
                await self._append(
                    writer,
                    replay,
                    CaptureRecord(
                        kind="gap", epoch=replay.epoch, received_ns=time.time_ns(), reason=reason
                    ),
                )
            await self._append(
                writer,
                replay,
                CaptureRecord(
                    kind="end", epoch=replay.epoch, received_ns=time.time_ns(), reason=reason
                ),
            )
            run.progress(status="sealing", messages=replay.messages, source_stop_reason=reason)
            await asyncio.to_thread(
                run.sealed, writer.current, writer.first_received_ns or replay.started_ns or 1
            )
            segment = writer.current.request.segment
            summary = {
                **replay.summary(),
                "run_identity": request.identity,
                "stop_reason": reason,
                "replay_verification": "pending",
                "actual_ready_ns": stop.ready_ns,
                "last_ready_ns": stop.last_ready_ns,
                "saved_bytes": writer.total_bytes,
                "saved_records": writer.total_records,
                "retained_unknown_tail_bytes": tail_bytes,
                "segments": 0 if segment is None else segment.ordinal + 1,
                "reached_stop_deadline": reason in ("stop_deadline", "duration_limit"),
            }
            run.finish(summary)
            return summary
        finally:
            run.close()

    async def _session(
        self,
        writer: CaptureSegmentWriter,
        replay: CaptureReplay,
        stop: CaptureRunStop,
        epoch: int,
        deadline: float,
    ) -> str:
        """Receive one native connection while the durable writer rotates independently."""
        socket: FeedSocket | None = None
        reader: asyncio.Task[None] | None = None
        ending: CaptureRecord | None = None
        queue = CaptureQueue(writer.run.request.config.queue_capacity)
        reason = "connect_failed_unknown_loss"
        try:
            try:
                budget = min(
                    float(writer.run.request.config.idle_seconds),
                    max(0, deadline - time.monotonic()),
                )
                if stop.ready_ns is None:
                    budget = min(budget, max(0, (stop.ready_by_ns - time.time_ns()) / 1e9))
                socket = await self._transport.open(budget)
                connection_deadline = time.monotonic() + budget
                for subscription in self._subscriptions(writer.run.request.config):
                    if stop.requested():
                        break
                    async with asyncio.timeout(max(0, connection_deadline - time.monotonic())):
                        await socket.send(self._codec.encode_json(subscription).decode())
            except OSError, WebSocketException, TimeoutError:
                reason = "connect_failed_unknown_loss"
            else:
                reader = asyncio.create_task(
                    ReceiptStream.frames(
                        socket,
                        queue,
                        writer.run.request.config,
                        epoch,
                        deadline,
                        writer.run.request.window.max_messages - replay.messages,
                        stop_requested=stop.requested,
                    )
                )
                while not queue.empty() or not reader.done():
                    record, _ = await queue.take()
                    if record.kind == "session_end":
                        ending, reason = record, record.reason
                        queue.acknowledged()
                        continue
                    try:
                        outcome = await self._append(writer, replay, record)
                    except OverflowError as error:
                        reason = self._limit_reason(error)
                        break
                    queue.acknowledged()
                    # A book synchronizes at its snapshot; a trade tape with no snapshot
                    # (OKX trades) synchronizes at its subscription acknowledgement.
                    if (
                        outcome in ("snapshot", "acknowledgement")
                        and replay.book.ready
                        and not replay.invalid
                    ):
                        stop.last_ready_ns = time.time_ns()
                        if stop.ready_ns is None:
                            stop.ready_ns = stop.last_ready_ns
                    await writer.progress(messages=replay.messages, ready_ns=stop.ready_ns)
                    if outcome == "invalid_frame":
                        reason = "invalid_stream_requires_snapshot"
                        reader.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await reader
                if reason == "supervisor_stop":
                    reason = stop.reason
        finally:
            if reader is not None:
                reader.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reader
            if socket is not None:
                await socket.close()
        if (
            reason
            not in (
                "duration_limit",
                "message_limit",
                "supervisor_stop",
                "stop_deadline",
                "readiness_deadline",
            )
            and not replay.invalid
        ):
            await self._append(
                writer,
                replay,
                CaptureRecord(
                    kind="gap",
                    epoch=epoch,
                    received_ns=time.time_ns() if ending is None else ending.received_ns,
                    reason=reason,
                ),
            )
        await self._append(
            writer,
            replay,
            CaptureRecord(
                kind="session_end",
                epoch=epoch,
                received_ns=time.time_ns() if ending is None else ending.received_ns,
                reason=reason,
            ),
        )
        return reason

    @staticmethod
    async def _append(
        writer: CaptureSegmentWriter, replay: CaptureReplay, record: CaptureRecord
    ) -> str:
        """Apply only after the original record has a durable cursor acknowledgement."""
        await writer.append(record)
        return replay.apply(record)

    @staticmethod
    def _limit_reason(error: OverflowError) -> str:
        """Map only writer-owned bounded refusals to durable fixed gap reasons."""
        return (
            "run_segment_limit_unknown_tail"
            if str(error) == "capture run segment limit"
            else "run_byte_limit_unknown_tail"
        )
