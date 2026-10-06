"""Rotate finite durable journals while receipt and native reconstruction continue."""

from __future__ import annotations

# standard library imports
import asyncio
import time

# project library imports
from market_data.contracts import CaptureRecord
from market_data.storage import CaptureJournal, CaptureRunJournal
from serialization import DomainCodec


class CaptureSegmentWriter:
    """Enforce segment and whole-run ceilings without resetting source state."""

    def __init__(
        self,
        run: CaptureRunJournal,
        current: CaptureJournal,
        *,
        previous_bytes: int,
        previous_records: int,
    ) -> None:
        """Bind one active segment after explicit provisioning and prefix verification."""
        self.run, self.current = run, current
        self.total_bytes = previous_bytes
        self.total_records = previous_records
        self.segment_messages = 0
        self.first_received_ns: int | None = None
        self.deadline = time.monotonic() + run.request.config.duration_seconds
        self._last_progress = 0.0
        self._codec = DomainCodec()

    async def append(self, record: CaptureRecord) -> None:
        """Commit each original record exactly once, rotating before a segment fills.

        Received frames remain in the existing bounded queue during publication.
        A rollover is storage only: it adds no session, end, gap or snapshot.
        """
        encoded_bytes = len(self._codec.encode_json(record)) + 1
        # Terminal controls may use the reserve; every other record may rotate.
        rotating = record.kind in ("frame", "snapshot", "session", "clock")
        reserve = 8192 if rotating else 0
        if self.total_bytes + encoded_bytes > self.run.request.window.max_bytes - reserve:
            raise OverflowError("capture run byte limit")
        config = self.run.request.config
        if rotating and (
            time.monotonic() >= self.deadline
            or self.segment_messages >= config.max_messages
            or self.current.size + encoded_bytes > config.max_bytes - 4096
        ):
            segment = self.current.request.segment
            if segment is None or segment.ordinal + 1 >= self.run.request.window.max_segments:
                raise OverflowError("capture run segment limit")
            await asyncio.to_thread(
                self.run.sealed, self.current, self.first_received_ns or record.received_ns
            )
            self.current = await asyncio.to_thread(self.run.start_segment, self.current)
            self.segment_messages = 0
            self.first_received_ns = None
            self.deadline = time.monotonic() + config.duration_seconds
        await asyncio.to_thread(self.current.append, record)
        if self.first_received_ns is None:
            self.first_received_ns = record.received_ns
        self.total_bytes += encoded_bytes
        self.total_records += 1
        self.segment_messages += record.kind in ("frame", "snapshot")

    async def progress(self, *, messages: int, ready_ns: int | None) -> None:
        """Persist observed progress at most once per second outside the per-record cursor."""
        if time.monotonic() - self._last_progress < 1:
            return
        self._last_progress = time.monotonic()
        await asyncio.to_thread(
            self.run.progress,
            status="collecting",
            recording_id=self.current.request.recording_id,
            segment=self.current.request.segment,
            committed_bytes=self.total_bytes,
            committed_records=self.total_records,
            messages=messages,
            actual_ready_ns=ready_ns,
        )
