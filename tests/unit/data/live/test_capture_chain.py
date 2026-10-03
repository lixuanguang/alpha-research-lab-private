"""Prove paper capture keeps its hooks and native continuity across segment rollover."""

from __future__ import annotations

# standard library imports
import asyncio
import multiprocessing
from datetime import UTC, datetime, timedelta
from multiprocessing.connection import Connection
from pathlib import Path
from typing import cast
from unittest.mock import patch

# third party library imports
import msgspec
import pytest
from msgspec.structs import replace

# project library imports
from applications.execute.source_service import SourceDelivery, capture_service
from configuration import CaptureConfig, CaptureRunConfig
from market_data.adapters.sources import BookAdapters, SourceAdapters
from market_data.adapters.transport import VenueSubscriptions, VenueTransport
from market_data.collection import CaptureRunner
from market_data.contracts import BookObservation, CaptureRecord, CaptureRunRequest, FeedSocket
from market_data.replay import SavedCaptureRun
from market_data.storage import CaptureJournal, CaptureRunJournal
from serialization import DomainCodec
from telemetry import HealthMetric, HealthMetrics, RuntimeMeasurementJournal

_ROOT = Path(__file__).parents[4]
_FRAMES: tuple[bytes, ...] = (
    b'{"event":"conf","status":"OK","flags":65536}',
    b'[7,"hb",1]',
    b'{"event":"subscribed","chanId":7,"channel":"book","symbol":"tBTCUSD","prec":"R0","freq":"F0","len":"25"}',
    b"[7,[[1,100,2],[2,101,-1]],2]",
    b"[7,[1,100,0.25],3]",
    b'[7,"hb",4]',
    b"[7,[2,101,-2],5]",
)


class CaptureChainFixture:
    """Build capture-chain requests, runners and durable journals."""

    @staticmethod
    def durable(root: Path, request: CaptureRunRequest) -> tuple[CaptureRecord, ...]:
        """Return each segment's sealed records, or its acknowledged prefix while active."""
        records: list[CaptureRecord] = []
        for journal in CaptureRunJournal(root, request).segments():
            if (journal.root / "manifest.json").exists():
                records.extend(journal.records(completed=True))
            else:
                # The interrupted view ends with a synthetic unknown-tail gap.
                records.extend(tuple(journal.records(completed=False))[:-1])
        return tuple(records)

    @staticmethod
    def request(*, segment_messages: int = 4, max_segments: int = 8) -> CaptureRunRequest:
        """Declare a finite paper run whose whole-run message limit ends it promptly."""
        now = datetime.now(UTC)
        config = replace(
            CaptureConfig.read(_ROOT / "configs/live/bitfinex-btc-usd.json"),
            max_messages=segment_messages,
            max_bytes=32768,
            max_frame_bytes=8192,
            queue_capacity=16,
            retries=0,
        )
        return CaptureRunRequest(
            config=config,
            window=CaptureRunConfig(
                start_at=now - timedelta(seconds=1),
                ready_by=now + timedelta(seconds=60),
                stop_at=now + timedelta(seconds=60),
                max_messages=len(_FRAMES),
                max_bytes=1_048_576,
                max_segments=max_segments,
                max_reconnects=0,
            ),
            run_id="00000000-0000-4000-8000-000000000041",
            implementation_identity="a" * 64,
        )

    @staticmethod
    def runner(
        transport: _Transport,
        *,
        observer: _Observer | None = None,
        health: HealthMetrics | None = None,
        measurements: RuntimeMeasurementJournal | None = None,
    ) -> CaptureRunner:
        """Compose the paper capture runner with its optional hooks."""
        return CaptureRunner(
            book_factory=BookAdapters.create,
            transport=transport,
            subscriptions=VenueSubscriptions(),
            observer=observer,
            health=health,
            measurements=measurements,
        )


class _Socket:
    """Deliver one authored native connection, then wait for the runner's own stop."""

    def __init__(self) -> None:
        """Bind the exact wire sequence and expose subscriptions and release."""
        self._frames = iter(_FRAMES)
        self.sent: list[str] = []
        self.closed = False

    async def recv(self) -> bytes:
        """Yield original native messages, then hold the connection open."""
        await asyncio.sleep(0)
        frame = next(self._frames, None)
        if frame is None:
            await asyncio.sleep(3600)
            raise AssertionError("runner failed to enforce its message limit")
        return frame

    async def send(self, message: str) -> None:
        """Retain outbound subscriptions to detect a reconnect at rollover."""
        self.sent.append(message)

    async def close(self) -> None:
        """Expose ownership release."""
        self.closed = True


class _Transport(VenueTransport):
    """Replace only public routing; the installed parser and journals stay real."""

    def __init__(self, config: CaptureConfig) -> None:
        """Bind the selected source and record every opened connection."""
        super().__init__(config)
        self.sockets: list[_Socket] = []

    async def open(self, timeout: float) -> FeedSocket:
        """Open a fresh native connection."""
        socket = _Socket()
        self.sockets.append(socket)
        return socket


class _DroppingSocket(_Socket):
    """Lose the connection once a full segment of authored messages has arrived."""

    def __init__(self, delivered: int) -> None:
        """Bind how many authored messages arrive before the disconnect."""
        super().__init__()
        self._remaining = delivered

    async def recv(self) -> bytes:
        """Yield the authored prefix, then fail as a dropped connection."""
        if self._remaining == 0:
            raise OSError("connection lost")
        self._remaining -= 1
        return await super().recv()


class _DroppingTransport(_Transport):
    """Open connections that drop after exactly one segment's message limit."""

    async def open(self, timeout: float) -> FeedSocket:
        """Open a fresh native connection that fails after the segment limit."""
        socket = _DroppingSocket(self.config.max_messages)
        self.sockets.append(socket)
        return socket


class _Observer:
    """Require every callback to follow its record's durable acknowledgement."""

    def __init__(self, root: Path, request: CaptureRunRequest) -> None:
        """Bind the run whose segment chain must already hold each observed record."""
        self.root, self.request = root, request
        self.records: list[CaptureRecord] = []
        self.rows: list[BookObservation] = []

    def observe(self, record: CaptureRecord, row: BookObservation) -> None:
        """Compare the record and its run-wide position with the durable chain."""
        durable = CaptureChainFixture.durable(self.root, self.request)
        assert durable[-1] == record
        assert row.position == len(self.rows) == len(durable) - 1
        assert row.received_ns == record.received_ns and row.epoch == record.epoch
        self.records.append(record)
        self.rows.append(row)


class TestCaptureChain:
    """Keep the paper path's semantics while its storage rotates under it."""

    def test_rollover_keeps_session_sequence_and_every_hook(self, tmp_path: Path) -> None:
        """One connection spans two segments; hooks see run-wide durable positions."""
        request = CaptureChainFixture.request()
        root = tmp_path / request.run_id
        transport, health = _Transport(request.config), HealthMetrics()
        observer = _Observer(root, request)
        path = tmp_path / "capture-measurements.jsonl"
        with RuntimeMeasurementJournal(path, sync_every=1) as measurements:
            result = asyncio.run(
                CaptureChainFixture.runner(
                    transport, observer=observer, health=health, measurements=measurements
                ).run_chain(request, tmp_path)
            )
        assert result.request == request and result.root == root
        assert len(transport.sockets) == 1 and transport.sockets[0].closed
        assert len(transport.sockets[0].sent) == 2
        assert result.summary["segments"] == 2
        assert result.summary["stop_reason"] == "message_limit"
        assert result.summary["replay_parity"] is True
        assert result.summary["source_sequence"] == 5
        assert result.summary["snapshots"] == 1 and result.summary["updates"] == 2
        assert result.summary["gaps"] == []

        journals = CaptureRunJournal(root, request).segments()
        records = tuple(
            record for journal in journals for record in journal.records(completed=True)
        )
        assert tuple(record.raw for record in records if record.kind == "frame") == _FRAMES
        assert [record.kind for record in records].count("session") == 1
        assert all(record.epoch == 0 for record in records)
        assert not any(
            record.kind in ("gap", "session_end", "end")
            for record in journals[0].records(completed=True)
        )
        assert not any(
            record.kind in ("session", "snapshot", "gap")
            for record in journals[1].records(completed=True)
        )
        assert tuple(observer.records) == records
        assert [row.position for row in observer.rows] == list(range(len(records)))
        assert [row.outcome for row in observer.rows][-2:] == ["session_end", "end"]
        assert health.snapshot()[HealthMetric.PERSISTED_RECORDS] == len(records)
        assert health.snapshot()[HealthMetric.PERSISTENCE_FAILED] == 0

        rows = tuple(
            msgspec.json.decode(line, type=dict[str, object])
            for line in path.read_bytes().splitlines()
        )
        boundaries = tuple(row for row in rows if row["kind"] == "capture_boundary")
        rollovers = tuple(row for row in rows if row["kind"] == "capture_rollover")
        assert [row["cursor"] for row in boundaries] == [
            row.position + 1
            for record, row in zip(observer.records, observer.rows, strict=True)
            if record.kind == "frame"
        ]
        assert all(row["record_fsync_ns"] is not None for row in boundaries)
        assert len(rollovers) == 1
        sealed = journals[0].committed_cursor().records
        assert rollovers[0]["segment"] == 1
        assert rollovers[0]["sealed_records"] == sealed
        assert rollovers[0]["cursor"] == sealed + 1
        rollover_ns = rollovers[0]["rollover_append_ns"]
        assert isinstance(rollover_ns, int) and rollover_ns > 0

        replay = SavedCaptureRun.read(root, book_factory=BookAdapters.create, max_seconds=30)
        assert replay.summary()["trace_identity"] == result.summary["trace_identity"]

    _START_SEGMENT = CaptureRunJournal.start_segment

    @staticmethod
    def _failed_finish(journal: CaptureJournal, received_ns: int) -> object:
        """Fail sealing the first segment; installed on the class, it binds the journal."""
        raise OSError("seal unavailable")

    @staticmethod
    def _failed_successor(run: CaptureRunJournal, previous: CaptureJournal | None) -> object:
        """Provision the first segment, then fail its successor; binds the run like a method."""
        if previous is not None:
            raise OSError("provision unavailable")
        return TestCaptureChain._START_SEGMENT(run, previous)

    @pytest.mark.parametrize("phase", ["seal", "provision"])
    def test_rollover_failure_raises_after_only_durable_records(
        self, tmp_path: Path, phase: str
    ) -> None:
        """A failed boundary is a persistence failure, never continuity or a lost callback."""
        request = CaptureChainFixture.request()
        root = tmp_path / request.run_id
        transport, health = _Transport(request.config), HealthMetrics()
        observer = _Observer(root, request)
        target = (
            patch.object(CaptureJournal, "finish", self._failed_finish)
            if phase == "seal"
            else patch.object(CaptureRunJournal, "start_segment", self._failed_successor)
        )
        runner = CaptureChainFixture.runner(transport, observer=observer, health=health)
        with target, pytest.raises(OSError, match=f"{phase} unavailable"):
            asyncio.run(runner.run_chain(request, tmp_path))
        assert transport.sockets[0].closed
        assert health.snapshot()[HealthMetric.PERSISTENCE_FAILED] == 1
        assert not (root / "run-summary.json").exists()
        journals = CaptureRunJournal(root, request).segments()
        assert len(journals) == 1
        assert (journals[0].root / "manifest.json").exists() is (phase == "provision")
        durable = CaptureChainFixture.durable(root, request)
        assert tuple(observer.records) == durable
        assert sum(record.kind == "frame" for record in durable) == request.config.max_messages
        assert durable[-1].raw == _FRAMES[request.config.max_messages - 1]

    def test_segment_limit_ends_with_storage_gap_and_verifiable_chain(self, tmp_path: Path) -> None:
        """A whole-run segment refusal is today's storage refusal, retained and replayable."""
        request = CaptureChainFixture.request(max_segments=1)
        transport = _Transport(request.config)
        result = asyncio.run(CaptureChainFixture.runner(transport).run_chain(request, tmp_path))
        assert result.summary["stop_reason"] == "storage_limit_unknown_tail"
        gaps = result.summary["gaps"]
        assert result.summary["segments"] == 1 and isinstance(gaps, list) and len(gaps) == 1
        assert transport.sockets[0].closed
        records = tuple(
            record
            for journal in CaptureRunJournal(result.root, request).segments()
            for record in journal.records(completed=True)
        )
        assert [record.kind for record in records][-3:] == ["gap", "session_end", "end"]
        assert records[-3].reason == "storage_limit_unknown_tail"
        SavedCaptureRun.read(result.root, book_factory=BookAdapters.create, max_seconds=30)

    def test_segment_limit_at_reconnect_ends_as_storage_refusal(self, tmp_path: Path) -> None:
        """A reconnect that would open a segment past the run limit is retained, not raised."""
        request = CaptureChainFixture.request(max_segments=1)
        request = replace(request, config=replace(request.config, retries=1))
        root = tmp_path / request.run_id
        transport, health = _DroppingTransport(request.config), HealthMetrics()
        observer = _Observer(root, request)
        result = asyncio.run(
            CaptureChainFixture.runner(transport, observer=observer, health=health).run_chain(
                request, tmp_path
            )
        )
        assert len(transport.sockets) == 1 and transport.sockets[0].closed
        assert result.summary["stop_reason"] == "storage_limit_unknown_tail"
        assert result.summary["segments"] == 1 and result.summary["replay_parity"] is True
        assert result.summary["gaps"] == [
            {"epoch": 0, "received_ns": record.received_ns, "reason": record.reason}
            for record in CaptureChainFixture.durable(root, request)
            if record.kind == "gap"
        ]
        records = CaptureChainFixture.durable(root, request)
        assert [record.kind for record in records][-4:] == ["gap", "session_end", "gap", "end"]
        assert [record.reason for record in records if record.kind == "gap"] == [
            "disconnect_unknown_loss",
            "storage_limit_unknown_tail",
        ]
        assert [record.kind for record in records].count("session") == 1
        assert tuple(observer.records) == records
        assert health.snapshot()[HealthMetric.PERSISTENCE_FAILED] == 1
        SavedCaptureRun.read(root, book_factory=BookAdapters.create, max_seconds=30)

    def test_chain_refuses_a_canonical_book_prefix(self, tmp_path: Path) -> None:
        """Prefix verification is bound to one recording directory."""
        request = CaptureChainFixture.request()
        runner = CaptureRunner(
            book_factory=BookAdapters.create,
            transport=_Transport(request.config),
            subscriptions=VenueSubscriptions(),
            snapshot_records=32,
            readers=SourceAdapters(),
        )
        with pytest.raises(ValueError, match="canonical book prefix"):
            asyncio.run(runner.run_chain(request, tmp_path))
        assert not (tmp_path / request.run_id).exists()

    def test_source_service_forwards_a_chain_and_retains_its_result(self, tmp_path: Path) -> None:
        """The paper source child sends each durable row once and keeps the chain summary."""
        request = CaptureChainFixture.request()
        receiver, sender = cast(
            "tuple[Connection[bytes, bytes], Connection[bytes, bytes]]",
            multiprocessing.Pipe(duplex=False),
        )
        asyncio.run(
            capture_service(
                request,
                tmp_path,
                sender,
                HealthMetrics(),
                _Transport(request.config),
            )
        )
        codec = DomainCodec()
        deliveries: list[SourceDelivery] = []
        with receiver:
            while True:
                try:
                    payload = receiver.recv_bytes()
                except EOFError:
                    break
                deliveries.append(codec.decode_json(payload, SourceDelivery))
        root = tmp_path / request.run_id
        assert tuple(delivery.record for delivery in deliveries) == CaptureChainFixture.durable(
            root, request
        )
        assert [delivery.book.position for delivery in deliveries] == list(range(len(deliveries)))
        summary = msgspec.json.decode(
            (tmp_path / "source-result.json").read_bytes(), type=dict[str, object]
        )
        assert summary["segments"] == 2 and summary["replay_parity"] is True
        assert summary["run_identity"] == request.identity
