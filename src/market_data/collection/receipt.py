"""Compose bounded capture, durable input and deterministic visible-order replay."""

from __future__ import annotations

# standard library imports
import asyncio
import time
from collections import deque
from collections.abc import Callable
from http.client import HTTPException

# third party library imports
from websockets.exceptions import WebSocketException

# project library imports
from configuration import CaptureConfig
from market_data.contracts import CaptureRecord, FeedSocket, SnapshotTransport
from telemetry import HealthMetric, HealthMetrics, RuntimeMeasurementJournal


class ReceiptClock:
    """Stamp one recording's receipts on a wall clock that never moves backwards.

    Received messages use ``receive``, which refuses a wall-clock step back so the
    capture can end its session with a visible gap instead of retaining a
    regressed receipt. Locally made records (sessions, gaps, ends and clocks) use
    ``stamp``, which never precedes an earlier receipt.
    """

    def __init__(self, after_ns: int = 0) -> None:
        """Start after an already retained receipt, such as a resumed recording's last."""
        self.last_ns = after_ns

    def receive(self) -> int | None:
        """Return the current receipt, or None when the wall clock moved backwards."""
        now_ns = time.time_ns()
        if now_ns < self.last_ns:
            return None
        self.last_ns = now_ns
        return now_ns

    def stamp(self) -> int:
        """Return a local record's receipt, never earlier than the previous one."""
        self.last_ns = max(self.last_ns, time.time_ns())
        return self.last_ns


class CaptureQueue(asyncio.Queue[CaptureRecord]):
    """Track actual queued bytes and monotonic age through the durable append."""

    def __init__(
        self,
        maxsize: int,
        health: HealthMetrics | None = None,
        measurements: RuntimeMeasurementJournal | None = None,
    ) -> None:
        """Bind one bounded event-loop queue and optional shared observation."""
        super().__init__(maxsize)
        self._health = health
        self._measurements = measurements
        self._receipts: deque[tuple[int, int]] = deque()
        self._put_clock: dict[int, int] = {}
        self._bytes = 0
        # Stamped records awaiting space; a woken put is still in flight until it resumes.
        self._putting = 0
        self.last_put_ns = time.monotonic_ns()

    @property
    def settled(self) -> bool:
        """Report whether nothing is queued or still being put, so a clock may follow."""
        return self.empty() and self._putting == 0

    async def put(self, item: CaptureRecord) -> None:
        """Count a stamped record as in flight until the queue accepts it."""
        self._putting += 1
        try:
            await super().put(item)
        finally:
            self._putting -= 1

    def put_received_nowait(self, item: CaptureRecord, received_at_ns: int) -> None:
        """Preserve the socket receipt clock across frame validation and queueing."""
        self._put_clock[id(item)] = received_at_ns
        try:
            self.put_nowait(item)
        finally:
            self._put_clock.pop(id(item), None)

    async def put_received(self, item: CaptureRecord, received_at_ns: int) -> None:
        """Preserve a completed snapshot's clock across bounded queue backpressure."""
        self._put_clock[id(item)] = received_at_ns
        try:
            await self.put(item)
        finally:
            self._put_clock.pop(id(item), None)

    def put_nowait(self, item: CaptureRecord) -> None:
        """Retain a monotonic receipt clock only after accepting the record."""
        super().put_nowait(item)
        self.last_put_ns = time.monotonic_ns()
        self._receipts.append((self._put_clock.pop(id(item), time.monotonic_ns()), len(item.raw)))
        self._bytes += len(item.raw)
        self._observe("accepted")

    async def take(self) -> tuple[CaptureRecord, int]:
        """Return the oldest frame and retain its age until durable acknowledgement."""
        record = await self.get()
        return record, self._receipts[0][0]

    def acknowledged(self) -> None:
        """Release exactly one entry after its durable append or deliberate terminal skip."""
        if self._measurements is not None:
            self._observe("durable_ready")
        _, size = self._receipts.popleft()
        self._bytes -= size
        self._observe("acknowledged")

    def _observe(self, phase: str) -> None:
        """Publish current in-flight bytes and oldest monotonic enqueue time."""
        oldest_ns = 0 if not self._receipts else self._receipts[0][0]
        if self._health is not None:
            self._health.set(HealthMetric.QUEUE_BYTES, self._bytes)
            self._health.set(HealthMetric.QUEUE_OLDEST_NS, oldest_ns)
        if self._measurements is not None:
            at_ns = time.monotonic_ns()
            self._measurements.record(
                {
                    "kind": "queue",
                    "phase": phase,
                    "at_ns": at_ns,
                    "pending_records": self.qsize(),
                    "in_flight_records": len(self._receipts) - self.qsize(),
                    "queued_bytes": self._bytes,
                    "oldest_age_ns": 0 if oldest_ns == 0 else max(0, at_ns - oldest_ns),
                }
            )


class ReceiptStream:
    """Receive bounded whole frames and snapshots before durable consumption."""

    @staticmethod
    async def frames(
        socket: FeedSocket,
        queue: asyncio.Queue[CaptureRecord],
        config: CaptureConfig,
        epoch: int,
        deadline: float,
        remaining: int,
        health: HealthMetrics | None = None,
        stop_requested: Callable[[], bool] | None = None,
        *,
        receipts: ReceiptClock,
    ) -> None:
        """Timestamp receipt independently of persistence; stop visibly on overload or disconnect.

        Args:
            socket: This epoch's open message connection.
            queue: Bounded queue shared with the durable consumer.
            config: Validated native spot source selection and resource budgets.
            epoch: Connection epoch within the current recording.
            deadline: Monotonic receive deadline in seconds.
            remaining: Maximum additional received WebSocket messages.
            health: Optional shared progress observed by an independent supervisor.
            stop_requested: Optional cooperative stop signal for a finite owner service.
            receipts: The recording's monotonic receipt clock.
        """
        reason = "message_limit"
        awaiting_pong = False
        received = 0
        queue_peak = 0 if health is None else health.snapshot()[HealthMetric.QUEUE]
        idle = min(config.idle_seconds, 20) if config.venue == "okx" else config.idle_seconds
        idle_deadline = time.monotonic() + idle
        try:
            while received < remaining:
                if stop_requested is not None and stop_requested():
                    reason = "supervisor_stop"
                    break
                budget = deadline - time.monotonic()
                if budget <= 0:
                    reason = "duration_limit"
                    break
                try:
                    wait_seconds = min(budget, max(0, idle_deadline - time.monotonic()))
                    if stop_requested is not None:
                        wait_seconds = min(wait_seconds, 0.1)
                    async with asyncio.timeout(wait_seconds):
                        message = await socket.recv()
                except TimeoutError:
                    if stop_requested is not None and stop_requested():
                        reason = "supervisor_stop"
                        break
                    if time.monotonic() < min(idle_deadline, deadline):
                        continue
                    if config.venue == "okx" and not awaiting_pong and time.monotonic() < deadline:
                        async with asyncio.timeout(max(0, deadline - time.monotonic())):
                            await socket.send("ping")
                        awaiting_pong = True
                        idle_deadline = time.monotonic() + idle
                        continue
                    reason = "duration_limit" if time.monotonic() >= deadline else "idle_timeout"
                    break
                awaiting_pong = False
                idle_deadline = time.monotonic() + idle
                received_at_ns = time.monotonic_ns()
                received_ns = receipts.receive()
                if received_ns is None:
                    reason = "receipt_clock_regressed"
                    break
                received += 1
                record = CaptureRecord(
                    kind="frame",
                    epoch=epoch,
                    received_ns=received_ns,
                    raw=message.encode() if isinstance(message, str) else message,
                )
                if health is not None:
                    health.set(
                        HealthMetric.RECEIVED_FRAMES,
                        health.snapshot()[HealthMetric.RECEIVED_FRAMES] + 1,
                    )
                if len(record.raw) > config.max_frame_bytes:
                    reason = "frame_limit_unknown_loss"
                    break
                try:
                    if isinstance(queue, CaptureQueue):
                        queue.put_received_nowait(record, received_at_ns)
                    else:
                        queue.put_nowait(record)
                    if health is not None:
                        health.set(HealthMetric.INGESTION, time.monotonic_ns())
                        queue_peak = max(queue_peak, queue.qsize())
                        health.set(HealthMetric.QUEUE, queue_peak)
                except asyncio.QueueFull:
                    reason = "overload_unknown_loss"
                    break
        except OSError, WebSocketException, TimeoutError:
            reason = "disconnect_unknown_loss"
        except Exception:
            # The consumer drains until session_end; ending without it would block
            # durable consumption forever. The fixed reason becomes a visible gap.
            reason = "receiver_failed_unknown_loss"
        await queue.put(
            CaptureRecord(
                kind="session_end", epoch=epoch, received_ns=receipts.stamp(), reason=reason
            )
        )

    @staticmethod
    async def snapshot(
        transport: SnapshotTransport,
        queue: asyncio.Queue[CaptureRecord],
        epoch: int,
        receipts: ReceiptClock,
    ) -> None:
        """Capture the independently fetched REST snapshot while WebSocket receipt continues.

        Args:
            transport: Explicit transport override for deterministic integration tests.
            queue: Bounded queue shared with the durable consumer.
            epoch: Connection epoch within the current recording.
            receipts: The recording's monotonic receipt clock.
        """
        try:
            raw = await asyncio.to_thread(transport.snapshot)
            received_at_ns = time.monotonic_ns()
            received_ns = receipts.receive()
            record = (
                CaptureRecord(kind="snapshot", epoch=epoch, received_ns=received_ns, raw=raw)
                if received_ns is not None
                else CaptureRecord(
                    kind="gap",
                    epoch=epoch,
                    received_ns=receipts.stamp(),
                    reason="receipt_clock_regressed",
                )
            )
        except OSError, ValueError, HTTPException:
            received_at_ns = time.monotonic_ns()
            record = CaptureRecord(
                kind="gap",
                epoch=epoch,
                received_ns=receipts.stamp(),
                reason="snapshot_failed_unknown_loss",
            )
        if isinstance(queue, CaptureQueue):
            await queue.put_received(record, received_at_ns)
        else:
            await queue.put(record)

    @staticmethod
    async def clock(
        queue: CaptureQueue,
        epoch: int,
        interval_ms: int,
        receipts: ReceiptClock,
        receiver: asyncio.Future[None],
    ) -> None:
        """Queue a ``clock`` record whenever a receiving feed stays idle for the interval.

        The record is stamped and queued in one step, and only into a settled queue:
        empty, with no stamped record still being put. A receiver or snapshot that
        stamped a record and waits for space, even one already woken, keeps the clock
        out, so every receipt stamped before a clock is queued ahead of it.

        Args:
            queue: Bounded queue shared with the durable consumer.
            epoch: Connection epoch within the current recording.
            interval_ms: The capture's idle interval in milliseconds.
            receipts: The recording's monotonic receipt clock.
            receiver: This epoch's receiver; no clock is queued once it is done.
        """
        interval_ns = interval_ms * 1_000_000
        while True:
            idle_ns = time.monotonic_ns() - queue.last_put_ns
            if idle_ns < interval_ns:
                await asyncio.sleep((interval_ns - idle_ns) / 1e9)
                continue
            if receiver.done():
                return
            if queue.settled:
                queue.put_received_nowait(
                    CaptureRecord(kind="clock", epoch=epoch, received_ns=receipts.stamp()),
                    time.monotonic_ns(),
                )
            else:
                await asyncio.sleep(interval_ns / 1e9)
