"""Compose bounded capture, durable input and deterministic visible-order replay."""

from __future__ import annotations

# standard library imports
import asyncio
import time
from collections import deque
from http.client import HTTPException

# third party library imports
from websockets.exceptions import WebSocketException

# project library imports
from configuration import CaptureConfig
from market_data.contracts import CaptureRecord, FeedSocket, SnapshotTransport
from telemetry import HealthMetric, HealthMetrics


class CaptureQueue(asyncio.Queue[CaptureRecord]):
    """Track actual queued bytes and monotonic age through the durable append."""

    def __init__(self, maxsize: int, health: HealthMetrics | None = None) -> None:
        """Bind one bounded event-loop queue and optional shared observation."""
        super().__init__(maxsize)
        self._health = health
        self._receipts: deque[tuple[int, int]] = deque()
        self._put_clock: dict[int, int] = {}
        self._bytes = 0

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
        self._receipts.append((self._put_clock.pop(id(item), time.monotonic_ns()), len(item.raw)))
        self._bytes += len(item.raw)
        self._observe()

    async def take(self) -> tuple[CaptureRecord, int]:
        """Return the oldest frame and retain its age until durable acknowledgement."""
        record = await self.get()
        return record, self._receipts[0][0]

    def acknowledged(self) -> None:
        """Release exactly one entry after its durable append or deliberate terminal skip."""
        _, size = self._receipts.popleft()
        self._bytes -= size
        self._observe()

    def _observe(self) -> None:
        """Publish current in-flight bytes and oldest monotonic enqueue time."""
        if self._health is not None:
            self._health.set(HealthMetric.QUEUE_BYTES, self._bytes)
            self._health.set(
                HealthMetric.QUEUE_OLDEST_NS, 0 if not self._receipts else self._receipts[0][0]
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
        """
        reason = "message_limit"
        awaiting_pong = False
        received = 0
        queue_peak = 0 if health is None else health.snapshot()[HealthMetric.QUEUE]
        try:
            while received < remaining:
                budget = deadline - time.monotonic()
                if budget <= 0:
                    reason = "duration_limit"
                    break
                try:
                    idle = (
                        min(config.idle_seconds, 20)
                        if config.venue == "okx"
                        else config.idle_seconds
                    )
                    async with asyncio.timeout(min(budget, idle)):
                        message = await socket.recv()
                except TimeoutError:
                    if config.venue == "okx" and not awaiting_pong and time.monotonic() < deadline:
                        async with asyncio.timeout(max(0, deadline - time.monotonic())):
                            await socket.send("ping")
                        awaiting_pong = True
                        continue
                    reason = "duration_limit" if time.monotonic() >= deadline else "idle_timeout"
                    break
                awaiting_pong = False
                received_at_ns = time.monotonic_ns()
                received += 1
                record = CaptureRecord(
                    kind="frame",
                    epoch=epoch,
                    received_ns=time.time_ns(),
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
        await queue.put(
            CaptureRecord(
                kind="session_end", epoch=epoch, received_ns=time.time_ns(), reason=reason
            )
        )

    @staticmethod
    async def snapshot(
        transport: SnapshotTransport,
        queue: asyncio.Queue[CaptureRecord],
        epoch: int,
    ) -> None:
        """Capture the independently fetched REST snapshot while WebSocket receipt continues.

        Args:
            transport: Explicit transport override for deterministic integration tests.
            queue: Bounded queue shared with the durable consumer.
            epoch: Connection epoch within the current recording.
        """
        try:
            raw = await asyncio.to_thread(transport.snapshot)
            received_at_ns = time.monotonic_ns()
            record = CaptureRecord(
                kind="snapshot", epoch=epoch, received_ns=time.time_ns(), raw=raw
            )
        except OSError, ValueError, HTTPException:
            received_at_ns = time.monotonic_ns()
            record = CaptureRecord(
                kind="gap",
                epoch=epoch,
                received_ns=time.time_ns(),
                reason="snapshot_failed_unknown_loss",
            )
        if isinstance(queue, CaptureQueue):
            await queue.put_received(record, received_at_ns)
        else:
            await queue.put(record)
