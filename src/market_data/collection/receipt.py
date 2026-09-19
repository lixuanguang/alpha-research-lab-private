"""Compose bounded capture, durable input and deterministic visible-order replay."""

from __future__ import annotations

# standard library imports
import asyncio
import time
from http.client import HTTPException

# third party library imports
from websockets.exceptions import WebSocketException

# project library imports
from configuration import CaptureConfig
from market_data.contracts import CaptureRecord, FeedSocket, SnapshotTransport
from telemetry import HealthMetric, HealthMetrics


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
                received += 1
                record = CaptureRecord(
                    kind="frame",
                    epoch=epoch,
                    received_ns=time.time_ns(),
                    raw=message.encode() if isinstance(message, str) else message,
                )
                if len(record.raw) > config.max_frame_bytes:
                    reason = "frame_limit_unknown_loss"
                    break
                try:
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
            record = CaptureRecord(
                kind="snapshot", epoch=epoch, received_ns=time.time_ns(), raw=raw
            )
        except OSError, ValueError, HTTPException:
            record = CaptureRecord(
                kind="gap",
                epoch=epoch,
                received_ns=time.time_ns(),
                reason="snapshot_failed_unknown_loss",
            )
        await queue.put(record)
