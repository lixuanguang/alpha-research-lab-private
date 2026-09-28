"""Exercise durable collection with deterministic disconnect, overload and disk faults."""

from __future__ import annotations

# standard library imports
import asyncio
import contextlib
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from http.client import IncompleteRead
from pathlib import Path
from threading import Event
from typing import Protocol
from unittest.mock import patch

# third party library imports
import pytest
from msgspec.structs import replace

# project library imports
from applications.collect import collect, monitored_capture
from configuration import CaptureConfig
from market_data.adapters.sources import BookAdapters, SourceAdapters
from market_data.adapters.transport import VenueSubscriptions, VenueTransport
from market_data.adapters.venues.coinbase import CoinbaseAccessError, CoinbaseCredentials
from market_data.books import CaptureReplay, NativeBook
from market_data.collection import CaptureRunner, ReceiptStream
from market_data.contracts import (
    BookObservation,
    CaptureRecord,
    CaptureRequest,
    FeedSocket,
    RawObject,
)
from market_data.datasets import BookDatasetManifest, SnapshotStore
from market_data.replay import SavedCapture
from market_data.storage import CaptureJournal, RawStore
from serialization import DomainCodec
from telemetry import HealthMetric, HealthMetrics

_ROOT = Path(__file__).parents[4]
_FRAMES: tuple[bytes, ...] = (
    b'{"event":"conf","status":"OK","flags":65536}',
    b'[7,"hb",1]',
    (
        b'{"event":"subscribed","chanId":7,"channel":"book","symbol":"tBTCU'
        b'SD","prec":"R0","freq":"F0","len":"25"}'
    ),
    b"[7,[[1,100,2],[2,101,-1]],2]",
    b"[7,[1,100,1.5],3]",
)


class ScriptedSocket:
    """Yield independent wire inputs with deterministic async scheduling."""

    def __init__(self, frames: tuple[bytes, ...]) -> None:
        """Bind one connection's finite message script.

        Args:
            frames: Finite exact messages for one synthetic connection.
        """
        self.frames = iter(frames)
        self.sent: list[str] = []
        self.closed = False

    async def send(self, message: str) -> None:
        """Retain subscription messages for non-secret transport assertions.

        Args:
            message: One outbound subscription/configuration message; never logged.
        """
        self.sent.append(message)

    async def recv(self) -> bytes:
        """End the scripted connection with an explicit transport fault.

        Returns:
            Next complete source message.

        Raises:
            OSError: The transport or durable storage operation fails.
        """
        await asyncio.sleep(0)
        result = next(self.frames, None)
        if result is None:
            raise OSError("synthetic disconnect")
        return result

    async def close(self) -> None:
        """Expose collector shutdown to the test."""
        self.closed = True


class ScriptedTransport(VenueTransport):
    """Replace only the external connection boundary; use actual collector/storage/replay."""

    def __init__(self, config: CaptureConfig, sessions: tuple[tuple[bytes, ...], ...]) -> None:
        """Bind a finite set of permitted recovery attempts.

        Args:
            config: Validated native spot source selection and resource budgets.
            sessions: Finite per-connection scripts for recovery tests.
        """
        super().__init__(config)
        self.sessions = iter(sessions)
        self.sockets: list[ScriptedSocket] = []

    async def open(self, timeout: float) -> FeedSocket:
        """Deliver the next isolated connection, failing when retry budget is exhausted.

        Args:
            timeout: Remaining connection budget in seconds.

        Returns:
            Bounded connection for the selected feed or synthetic session.

        Raises:
            OSError: The transport or durable storage operation fails.
        """
        frames = next(self.sessions, None)
        if frames is None:
            raise OSError("synthetic connection failure")
        socket = ScriptedSocket(frames)
        self.sockets.append(socket)
        return socket


class HoldingSocket(ScriptedSocket):
    """Hold a native feed open after accepted frames until its owner requests stop."""

    def __init__(self, frames: tuple[bytes, ...]) -> None:
        """Expose the point where every authored frame has reached the reader."""
        super().__init__(frames)
        self.all_frames_received = asyncio.Event()

    async def recv(self) -> bytes:
        """Keep the feed quiet after its finite prefix without fabricating disconnect."""
        await asyncio.sleep(0)
        result = next(self.frames, None)
        if result is not None:
            return result
        self.all_frames_received.set()
        await asyncio.Event().wait()
        raise AssertionError("held source should be cancelled on finite stop")


class HoldingTransport(VenueTransport):
    """Serve one open synthetic feed through the actual capture runner."""

    def __init__(self, config: CaptureConfig, socket: HoldingSocket) -> None:
        """Bind the configured venue to its retained native message prefix."""
        super().__init__(config)
        self.socket = socket

    async def open(self, timeout: float) -> FeedSocket:
        """Return the same bounded source until the cooperative stop closes it."""
        return self.socket


class RecordingObserver:
    """Retain each live canonical boundary for exact completed replay comparison."""

    def __init__(self) -> None:
        """Start with no inferred source delivery."""
        self.records: list[CaptureRecord] = []
        self.rows: list[BookObservation] = []

    def observe(self, record: CaptureRecord, row: BookObservation) -> None:
        """Keep only records actually published after their durable append."""
        self.records.append(record)
        self.rows.append(row)


class StalledSubscriptionSocket(ScriptedSocket):
    """Hold the second outbound message until the capture deadline cancels it."""

    async def send(self, message: str) -> None:
        """Send the configuration frame, then stall subscription under backpressure.

        Args:
            message: Outbound non-secret configuration or subscription JSON.
        """
        await super().send(message)
        if len(self.sent) == 2:
            await asyncio.Event().wait()


class FailingJournal(CaptureJournal):
    """Fail the first market append after durable session metadata exists."""

    def append(self, record: CaptureRecord) -> None:
        """Represent a disk failure while preserving the last committed prefix.

        Args:
            record: One complete received message or scoped session transition.

        Raises:
            OSError: The transport or durable storage operation fails.
        """
        if record.kind == "frame":
            raise OSError("synthetic disk full")
        super().append(record)


class _ReplayReader(Protocol):
    """Retain the saved-reader signature at the blocked finalization boundary."""

    def __call__(
        self,
        root: Path,
        *,
        book_factory: Callable[[CaptureConfig], NativeBook],
        completed: bool = True,
    ) -> CaptureReplay:
        """Read with explicit reconstruction and completion requirements."""
        ...


class BlockingReplayReader:
    """Hold offline replay at a deterministic finalization boundary."""

    def __init__(
        self,
        read: _ReplayReader,
        started: Event,
        release: Event,
    ) -> None:
        """Bind the original reader and synchronization events for one invocation.

        Args:
            read: Original offline replay reader retained after patching.
            started: Event set when the deliberately slow boundary is entered.
            release: Event that lets the original reader resume.
        """
        self._read = read
        self._started = started
        self._release = release

    def __call__(
        self,
        root: Path,
        *,
        book_factory: Callable[[CaptureConfig], NativeBook],
        completed: bool = True,
    ) -> CaptureReplay:
        """Wait outside the event loop, then preserve the original replay contract.

        Args:
            book_factory: Explicit native state constructor.
            completed: Whether finalization requires a closed journal.
            root: Completed capture directory to replay.

        Returns:
            The original offline replay result after the synchronization barrier.

        Raises:
            AssertionError: The test did not release the deterministic boundary in time.
        """
        self._started.set()
        if not self._release.wait(5):
            raise AssertionError("finalization replay boundary was not released")
        return self._read(root, book_factory=book_factory, completed=completed)


class TestCapture:
    """Check observable recording and installed-library contracts on saved inputs."""

    @staticmethod
    def config() -> CaptureConfig:
        """Use the maintained source selection with a finite deterministic fixture budget.

        Returns:
            Validated maintained source config with bounded fixture limits.
        """
        return replace(
            CaptureConfig.read(_ROOT / "configs/live/bitfinex-btc-usd.json"),
            max_messages=5,
            retries=0,
        )

    def test_durable_capture_parity_and_tamper(self, tmp_path: Path) -> None:
        """Store actual framed inputs and reproduce every message-boundary state offline."""
        config = self.config()
        transport = ScriptedTransport(config, (_FRAMES,))
        result = asyncio.run(
            collect(config, tmp_path, implementation_identity="a" * 64, transport=transport)
        )
        assert result["synchronized"] is True
        assert result["orders"] == 2
        assert result["gaps"] == []
        assert result["replay_parity"] is True
        root = next(tmp_path.iterdir())
        replay = SavedCapture.read(root, book_factory=BookAdapters.create)
        assert replay.summary()["trace_identity"] == result["trace_identity"]
        assert all(socket.closed for socket in transport.sockets)
        descriptor = DomainCodec().decode_json((root / "manifest.json").read_bytes(), RawObject)
        digest = descriptor.sha256
        assert isinstance(digest, str)
        os.chmod(root / digest, 0o600)
        (root / digest).write_bytes(b"tampered")
        with pytest.raises(ValueError, match="size mismatch"):
            SavedCapture.read(root, book_factory=BookAdapters.create)

    def test_health_tracks_durable_economic_progress(self, tmp_path: Path) -> None:
        """Expose fixed-size progress to a caller without conflating receipt and market clocks."""
        config, health = self.config(), HealthMetrics()
        initial = health.snapshot()
        result = asyncio.run(
            collect(
                config,
                tmp_path,
                implementation_identity="a" * 64,
                transport=ScriptedTransport(config, (_FRAMES,)),
                health=health,
            )
        )
        final = health.snapshot()
        assert result["synchronized"] is True
        assert final[HealthMetric.INGESTION] > initial[HealthMetric.INGESTION]
        assert final[HealthMetric.PERSISTENCE] >= final[HealthMetric.INGESTION]
        assert final[HealthMetric.MARKET] > initial[HealthMetric.MARKET]
        assert final[HealthMetric.FINALIZING] == 1
        assert final[HealthMetric.INVALID] == final[HealthMetric.PERSISTENCE_FAILED] == 0
        assert final[HealthMetric.RECEIVED_FRAMES] > 0
        assert final[HealthMetric.DURABLE_FRAMES] > 0
        assert final[HealthMetric.PERSISTED_RECORDS] >= final[HealthMetric.DURABLE_FRAMES]
        assert final[HealthMetric.RECEIPT_DURABLE_LAG_NS] >= 0
        assert final[HealthMetric.QUEUE_BYTES] == final[HealthMetric.QUEUE_OLDEST_NS] == 0
        assert final[HealthMetric.DUPLICATES] == result["duplicates"]
        assert final[HealthMetric.GAPS] == 0 and result["gaps"] == []

    def test_cooperative_stop_drains_native_prefix_and_terminal_delivery(
        self, tmp_path: Path
    ) -> None:
        """Every durably completed record reaches the observer before a finite stop exits."""
        asyncio.run(self._cooperative_stop_drains_native_prefix(tmp_path))

    async def _cooperative_stop_drains_native_prefix(self, tmp_path: Path) -> None:
        """Signal stop after all frames enter the source queue and compare saved replay."""
        config = replace(self.config(), max_messages=20, duration_seconds=5)
        request = CaptureRequest(
            config=config,
            recording_id="11111111-1111-4111-8111-111111111111",
            implementation_identity="a" * 64,
        )
        socket = HoldingSocket(_FRAMES)
        observer = RecordingObserver()
        stop = Event()
        runner = CaptureRunner(
            book_factory=BookAdapters.create,
            transport=HoldingTransport(config, socket),
            subscriptions=VenueSubscriptions(),
            observer=observer,
        )
        task = asyncio.create_task(runner.run(request, tmp_path, stop_requested=stop.is_set))
        try:
            await asyncio.wait_for(socket.all_frames_received.wait(), 2)
            stop.set()
            result = await asyncio.wait_for(task, 3)
        finally:
            stop.set()
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        retained = tuple(CaptureJournal(result.root, request).records())
        assert tuple(observer.records) == retained
        assert tuple(row.position for row in observer.rows) == tuple(range(len(retained)))
        assert [record.kind for record in retained[-2:]] == ["session_end", "end"]
        assert all(record.reason == "supervisor_stop" for record in retained[-2:])
        assert result.summary["stop_reason"] == "supervisor_stop"
        assert result.summary["replay_parity"] is True
        assert result.summary["gaps"] == []
        assert socket.closed is True

    def test_heartbeat_continues_during_offloaded_finalization(self, tmp_path: Path) -> None:
        """Keep process liveness advancing while saved-input replay is deliberately blocked."""
        asyncio.run(self._heartbeat_during_finalization(tmp_path))

    async def _heartbeat_during_finalization(self, tmp_path: Path) -> None:
        """Synchronize with the worker boundary before observing the heartbeat task."""
        started, release = Event(), Event()
        health = HealthMetrics()
        reader = BlockingReplayReader(SavedCapture.read, started, release)
        task = asyncio.create_task(
            monitored_capture(
                self.config(),
                tmp_path,
                health,
                None,
                ScriptedTransport(self.config(), (_FRAMES,)),
            )
        )
        try:
            with patch("market_data.collection.runner.SavedCapture.read", side_effect=reader):
                assert await asyncio.to_thread(started.wait, 5)
                before = health.snapshot()
                await asyncio.sleep(0.35)
                during = health.snapshot()
                assert during[HealthMetric.FINALIZING] == 1
                assert during[HealthMetric.HEARTBEAT] > before[HealthMetric.HEARTBEAT]
                release.set()
                await task
        finally:
            release.set()
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    def test_cancellation_waits_for_offloaded_finalization(self, tmp_path: Path) -> None:
        """Wait for a blocked finalizer to finish before cancellation returns to its caller."""
        asyncio.run(self._cancellation_waits_for_finalization(tmp_path))

    async def _cancellation_waits_for_finalization(self, tmp_path: Path) -> None:
        """Cancel after entering replay and release the worker after cancellation is pending."""
        started, release = Event(), Event()
        health = HealthMetrics()
        reader = BlockingReplayReader(SavedCapture.read, started, release)
        task = asyncio.create_task(
            collect(
                self.config(),
                tmp_path,
                implementation_identity="a" * 64,
                transport=ScriptedTransport(self.config(), (_FRAMES,)),
                health=health,
            )
        )
        try:
            with patch("market_data.collection.runner.SavedCapture.read", side_effect=reader):
                assert await asyncio.to_thread(started.wait, 5)
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
                release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
        finally:
            release.set()
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        root = next(tmp_path.iterdir())
        assert (root / "manifest.json").exists() and (root / "summary.json").exists()

    def test_finalization_persistence_failure_propagates(self, tmp_path: Path) -> None:
        """Propagate terminal publication errors and expose them to the health watchdog."""
        config, health = self.config(), HealthMetrics()
        with patch.object(
            CaptureJournal, "finish", side_effect=OSError("synthetic final disk full")
        ):
            with pytest.raises(OSError, match="final disk full"):
                asyncio.run(
                    collect(
                        config,
                        tmp_path,
                        implementation_identity="a" * 64,
                        transport=ScriptedTransport(config, (_FRAMES,)),
                        health=health,
                    )
                )
        values = health.snapshot()
        assert values[HealthMetric.FINALIZING] == 1
        assert values[HealthMetric.PERSISTENCE_FAILED] == 1
        root = next(tmp_path.iterdir())
        assert not (root / "manifest.json").exists()

    def test_subscription_deadline(self, tmp_path: Path) -> None:
        """Cancel blocked subscription sends and retain an unavailable closed session."""
        asyncio.run(self._subscription_deadline(tmp_path))

    async def _subscription_deadline(self, tmp_path: Path) -> None:
        """An outer guard makes a missing subscription timeout fail without hanging tests."""
        config = replace(self.config(), duration_seconds=1)
        socket = StalledSubscriptionSocket(())
        transport = ScriptedTransport(config, ())
        with patch.object(transport, "open", return_value=socket):
            async with asyncio.timeout(5):
                result = await collect(
                    config, tmp_path, implementation_identity="a" * 64, transport=transport
                )
        assert len(socket.sent) == 2 and socket.closed
        assert result["messages"] == 0 and result["synchronized"] is False
        assert result["stop_reason"] == "connect_failed_unknown_loss"
        assert result["gaps"] and result["replay_parity"] is True
        saved = SavedCapture.read(next(tmp_path.iterdir()), book_factory=BookAdapters.create)
        assert saved.gaps[0]["reason"] == "connect_failed_unknown_loss"

    @pytest.mark.parametrize(
        "raw",
        [
            b'{"event":"info","version":3,"platform":{"status":1}}',
            b'{"event":"error","code":10300,"msg":"Subscription failed"}',
        ],
    )
    def test_rejected_source_session(self, tmp_path: Path, raw: bytes) -> None:
        """Keep incompatible negotiation visible without admitting a book."""
        config = self.config()
        transport = ScriptedTransport(config, ())
        socket = ScriptedSocket(())
        burst: tuple[bytes, ...] = (raw, *_FRAMES)
        with (
            patch.object(transport, "open", return_value=socket),
            patch.object(socket, "recv", side_effect=burst),
        ):
            result = asyncio.run(
                collect(config, tmp_path, implementation_identity="a" * 64, transport=transport)
            )
        assert result["messages"] == 5 and result["synchronized"] is False
        root = next(tmp_path.iterdir())
        request = DomainCodec().decode_json((root / "request.json").read_bytes(), CaptureRequest)
        assert [r.raw for r in CaptureJournal(root, request).records() if r.kind == "frame"] == [
            raw,
            *_FRAMES[:4],
        ]
        assert result["stop_reason"] == "invalid_stream_requires_snapshot"
        assert result["gaps"] and result["replay_parity"] is True
        assert socket.closed

    def test_disconnect_resubscription(self, tmp_path: Path) -> None:
        """A fresh snapshot recovers state while the old session's unknown gap survives."""
        config = replace(self.config(), retries=1, max_messages=8)
        transport = ScriptedTransport(config, (_FRAMES[:3], _FRAMES))
        result = asyncio.run(
            collect(config, tmp_path, implementation_identity="a" * 64, transport=transport)
        )
        assert result["epochs"] == 2
        assert result["synchronized"] is True
        assert result["gaps"]
        assert result["replay_parity"] is True
        assert len(transport.sockets) == 2
        assert all(len(socket.sent) == 2 for socket in transport.sockets)
        assert result["retry_exhausted"] is False

    @pytest.mark.parametrize("is_exact", [True, False])
    def test_duplicate_delivery(self, tmp_path: Path, is_exact: bool) -> None:
        """Retain duplicate R0 bytes while applying one mutation or refusing a conflict."""
        config = replace(self.config(), max_messages=6)
        repeated = _FRAMES[-1] if is_exact else b"[7,[1,100,1.4],3]"
        result = asyncio.run(
            collect(
                config,
                tmp_path,
                implementation_identity="a" * 64,
                transport=ScriptedTransport(config, ((*_FRAMES, repeated),)),
            )
        )
        assert result["messages"] == 6 and result["updates"] == 1
        assert result["duplicates"] == int(is_exact)
        assert result["synchronized"] is is_exact
        assert result["retry_exhausted"] is not is_exact
        root = next(tmp_path.iterdir())
        request = DomainCodec().decode_json((root / "request.json").read_bytes(), CaptureRequest)
        assert [r.raw for r in CaptureJournal(root, request).records() if r.kind == "frame"] == [
            *_FRAMES,
            repeated,
        ]

    def test_retry_exhaustion(self, tmp_path: Path) -> None:
        """Connection failures create finite unavailable epochs and visible terminal status."""
        config = replace(self.config(), retries=1)
        result = asyncio.run(
            collect(
                config,
                tmp_path,
                implementation_identity="a" * 64,
                transport=ScriptedTransport(config, ()),
            )
        )
        assert result["epochs"] == 2
        assert result["synchronized"] is False
        assert result["messages"] == 0
        assert result["gaps"]

    def test_persistence_failure_preserves_incomplete_prefix(self, tmp_path: Path) -> None:
        """No manifest is published after disk failure; offline inspection reports unknown loss."""
        config = self.config()
        transport = ScriptedTransport(config, (_FRAMES,))
        consumer = CaptureReplay(config, book_factory=BookAdapters.create)
        with (
            patch("market_data.collection.runner.CaptureJournal", FailingJournal),
            patch("market_data.collection.runner.CaptureReplay", return_value=consumer),
        ):
            with pytest.raises(OSError, match="disk full"):
                asyncio.run(
                    collect(config, tmp_path, implementation_identity="a" * 64, transport=transport)
                )
        root = next(tmp_path.iterdir())
        assert consumer.messages == 0
        assert not (root / "manifest.json").exists()
        replay = SavedCapture.read(root, book_factory=BookAdapters.create, completed=False)
        assert replay.gaps[0]["reason"] == "interrupted_persistence_unknown_tail"
        assert not replay.book.ready
        assert all(socket.closed for socket in transport.sockets)

    def test_same_day_restart_preserves_prior_segment(self, tmp_path: Path) -> None:
        """Two invocations publish distinct identities without replacing the first input."""
        config = self.config()
        results = []
        for _ in range(2):
            results.append(
                asyncio.run(
                    collect(
                        config,
                        tmp_path,
                        implementation_identity="a" * 64,
                        transport=ScriptedTransport(config, (_FRAMES,)),
                    )
                )
            )
        assert results[0]["request_identity"] != results[1]["request_identity"]
        assert len(list(tmp_path.iterdir())) == 2
        for root in tmp_path.iterdir():
            assert SavedCapture.read(root, book_factory=BookAdapters.create).messages == len(
                _FRAMES
            )

    @pytest.mark.parametrize("invalid", [b"[7,[[1,-100,2]],2]", b"[7,[[1,100,0]],2]", b"not JSON"])
    def test_invalid_units_and_schema_retain_raw_diagnosis(
        self, tmp_path: Path, invalid: bytes
    ) -> None:
        """Raw invalid inputs survive the durable boundary while downstream state is blocked."""
        config = self.config()
        result = asyncio.run(
            collect(
                config,
                tmp_path,
                implementation_identity="a" * 64,
                transport=ScriptedTransport(config, ((*_FRAMES[:3], invalid),)),
            )
        )
        root = next(tmp_path.iterdir())
        request = DomainCodec().decode_json((root / "request.json").read_bytes(), CaptureRequest)
        records = list(CaptureJournal(root, request).records())
        assert [r.raw for r in records if r.kind == "frame"][-1] == invalid
        assert result["synchronized"] is False and result["gaps"]
        assert result["replay_parity"] is True

    def test_slow_consumer_receipt_remains_bounded(self, tmp_path: Path) -> None:
        """A blocked consumer cannot stall receipt or hide queue overflow behind a good book."""
        applying, overflow = Event(), Event()
        config = replace(self.config(), queue_capacity=1, max_messages=100)

        class PressureSocket(ScriptedSocket):
            """Synchronize a source burst with an actual blocked downstream invocation."""

            delivered = 0

            async def recv(self) -> bytes:
                """Wait for downstream processing, then fill and overflow its bounded queue.

                Returns:
                    One exact frame in the deliberate burst.
                """
                if self.delivered == 1:
                    assert await asyncio.to_thread(applying.wait, 5)
                raw = await super().recv()
                self.delivered += 1
                if self.delivered == 3:
                    overflow.set()
                return raw

        class SlowReplay(CaptureReplay):
            """Inspect persistence before blocking the first downstream message."""

            def apply(self, record: CaptureRecord) -> str:
                """Check the durable prefix before the live consumer can acknowledge a frame.

                Args:
                    record: One message delivered by capture or offline replay.

                Returns:
                    Normal replay classification after the deterministic barrier.
                """
                root = next(tmp_path.iterdir())
                if not (root / "manifest.json").exists():
                    request = DomainCodec().decode_json(
                        (root / "request.json").read_bytes(), CaptureRequest
                    )
                    assert (
                        list(CaptureJournal(root, request).records(completed=False))[-2] == record
                    )
                    if record.kind == "frame" and self.messages == 0:
                        applying.set()
                        assert overflow.wait(5), "consumer blocked receipt event loop"
                return super().apply(record)

        socket = PressureSocket(_FRAMES)
        transport = ScriptedTransport(config, ())
        with (
            patch.object(transport, "open", return_value=socket),
            patch("market_data.collection.runner.CaptureReplay", SlowReplay),
        ):
            result = asyncio.run(
                collect(config, tmp_path, implementation_identity="a" * 64, transport=transport)
            )
        assert socket.delivered == 3 and socket.closed
        assert result["messages"] == 2 and result["stop_reason"] == "overload_unknown_loss"
        assert result["gaps"] and result["replay_parity"] is True

    def test_truncated_tail(self, tmp_path: Path) -> None:
        """Process death in an append preserves readable records and explicitly rejects the tail."""
        request = CaptureRequest(
            config=self.config(),
            recording_id="00000000-0000-4000-8000-000000000001",
            implementation_identity="a" * 64,
        )
        root = tmp_path / "attempt"
        journal = CaptureJournal(root, request)
        journal.start()
        journal.append(CaptureRecord(kind="session", epoch=0, received_ns=1))
        with (root / "journal.jsonl").open("ab") as output:
            output.write(b'{"kind":"frame"')
        replay = SavedCapture.read(root, book_factory=BookAdapters.create, completed=False)
        assert replay.messages == 0
        assert len(replay.gaps) == 1
        assert not replay.ended

    def test_storage_limit(self, tmp_path: Path) -> None:
        """A bounded journal reserves room for a visible terminal gap, without silent clipping."""
        config = replace(self.config(), max_bytes=8192, max_frame_bytes=2048, max_messages=100)
        frames = _FRAMES + tuple(
            b'{"event":"info","unused":"' + b"x" * 1000 + b'"}' for _ in range(10)
        )
        result = asyncio.run(
            collect(
                config,
                tmp_path,
                implementation_identity="a" * 64,
                transport=ScriptedTransport(config, (frames,)),
            )
        )
        assert result["stop_reason"] == "storage_limit_unknown_tail"
        root = next(tmp_path.iterdir())
        assert (root / "journal.jsonl").stat().st_size <= config.max_bytes
        assert result["gaps"]

    def test_missing_auth_before_io(self, tmp_path: Path) -> None:
        """Coinbase missing auth neither creates an attempt nor opens a socket."""
        config = CaptureConfig.read(_ROOT / "configs/live/coinbase-btc-usd.json")
        with pytest.raises(CoinbaseAccessError):
            asyncio.run(collect(config, tmp_path, implementation_identity="a" * 64))
        assert list(tmp_path.iterdir()) == []

    def test_overload(self) -> None:
        """A full application queue stops receipt and emits unknown-loss metadata."""
        asyncio.run(self._overload())

    async def _overload(self) -> None:
        """Hold the consumer until the bounded producer observes the full queue."""
        config = replace(self.config(), queue_capacity=1)
        queue: asyncio.Queue[CaptureRecord] = asyncio.Queue(1)
        task = asyncio.create_task(
            ReceiptStream.frames(ScriptedSocket(_FRAMES), queue, config, 0, float("inf"), 5)
        )
        for _ in range(5):
            await asyncio.sleep(0)
        first = await queue.get()
        assert first.kind == "frame"
        ending = await queue.get()
        assert ending.reason == "overload_unknown_loss"
        await task


class SnapshotSocket(ScriptedSocket):
    """Keep the synthetic feed open until the snapshot precedes its final message."""

    def __init__(self, frames: tuple[bytes, ...], snapshot_queued: asyncio.Event) -> None:
        """Bind an explicit ordering barrier rather than relying on worker-thread speed.

        Args:
            frames: Complete finite source script.
            snapshot_queued: Signal that the actual snapshot receiver enqueued its result.
        """
        super().__init__(frames)
        self.remaining = len(frames)
        self.snapshot_queued = snapshot_queued

    async def recv(self) -> bytes:
        """Deliver the final update only after the independent snapshot is queued.

        Returns:
            Next exact source frame.
        """
        if self.remaining == 1:
            await self.snapshot_queued.wait()
        self.remaining -= 1
        return await super().recv()


class CoinbaseScript(VenueTransport):
    """Exercise concurrent snapshot fetching while preserving streamed L3 receipt order."""

    def __init__(self, config: CaptureConfig) -> None:
        """Bind the actual config and deterministic snapshot source.

        Args:
            config: Explicit Coinbase selection and bounded capture limits.
        """
        super().__init__(config)
        self._receive_snapshot = ReceiptStream.snapshot
        self.snapshot_queued = asyncio.Event()
        self.socket = SnapshotSocket(
            (
                (_ROOT / "tests/fixtures/market_data/coinbase/coinbase-schema.json").read_bytes(),
                b'{"type":"subscriptions","channels":[{"name":"level3",'
                b'"product_ids":["BTC-USD"]}]}',
                *(b'["noop","BTC-USD","' + str(i).encode() + b'",null]' for i in range(8, 30)),
            ),
            self.snapshot_queued,
        )

    async def enqueue_snapshot(
        self, transport: VenueTransport, queue: asyncio.Queue[CaptureRecord], epoch: int
    ) -> None:
        """Signal the socket only after the real snapshot receiver has queued its input.

        Args:
            transport: The collector's selected synthetic REST source.
            queue: The collector's actual bounded persistence queue.
            epoch: Current connection epoch.
        """
        await self._receive_snapshot(transport, queue, epoch)
        self.snapshot_queued.set()

    async def open(self, timeout: float) -> FeedSocket:
        """Return the bounded synthetic socket.

        Args:
            timeout: Remaining receive budget; no real network is accessed.

        Returns:
            The scripted L3 connection.
        """
        return self.socket

    def snapshot(self) -> bytes:
        """Supply the independent complete L3 snapshot.

        Returns:
            Exact synthetic REST bytes with snapshot sequence ten.
        """
        return (_ROOT / "tests/fixtures/market_data/coinbase/coinbase-snapshot.json").read_bytes()


class TestCoinbaseCapture:
    """Verify the authenticated pipeline composition independently of live eligibility."""

    def test_snapshot_protocol_failure(self) -> None:
        """Turn a truncated HTTP response into a queued gap instead of orphaning the consumer."""
        config = CaptureConfig.read(_ROOT / "configs/live/coinbase-btc-usd.json")
        queue: asyncio.Queue[CaptureRecord] = asyncio.Queue(1)
        transport = VenueTransport(config)
        with patch.object(transport, "snapshot", side_effect=IncompleteRead(b"partial")):
            asyncio.run(ReceiptStream.snapshot(transport, queue, 2))
        record = queue.get_nowait()
        assert record.kind == "gap" and record.epoch == 2
        assert record.reason == "snapshot_failed_unknown_loss" and not record.raw

    def test_snapshot_acquisition_and_replay(self, tmp_path: Path) -> None:
        """A concurrent REST response bridges persisted compact updates with exact parity."""
        from_config = CaptureConfig.read(_ROOT / "configs/live/coinbase-btc-usd.json")
        config = replace(from_config, retries=0, max_messages=24)
        transport = CoinbaseScript(config)
        with patch(
            "market_data.collection.receipt.ReceiptStream.snapshot", transport.enqueue_snapshot
        ):
            result = asyncio.run(
                collect(
                    config,
                    tmp_path,
                    implementation_identity="a" * 64,
                    credentials=CoinbaseCredentials(
                        "fixture", b"fixture-secret", "fixture-passphrase"
                    ),
                    transport=transport,
                )
            )
        assert result["snapshots"] == 1
        assert result["messages"] == config.max_messages
        assert result["orders"] == 1
        assert result["replay_parity"] is True
        assert result["synchronized"] is True
        assert result["gaps"] == []
        assert result["stop_reason"] == "message_limit"
        assert transport.socket.closed
        root = next(tmp_path.iterdir())
        journal = (root / "journal.jsonl").read_bytes()
        assert b"fixture-secret" not in journal
        assert b"fixture-passphrase" not in journal

    def test_capture_publishes_selected_book_prefix(self, tmp_path: Path) -> None:
        """Publish a bounded live result through the shared atomic snapshot boundary."""
        snapshots = tmp_path / "snapshots"
        snapshots.mkdir()
        config = TestCapture.config()
        result = asyncio.run(
            collect(
                config,
                tmp_path / "captures",
                implementation_identity="a" * 64,
                transport=ScriptedTransport(config, (_FRAMES,)),
                snapshot_directory=snapshots,
                snapshot_records=32,
            )
        )
        identity, directory = result["snapshot_identity"], result["capture_directory"]
        assert isinstance(identity, str) and isinstance(directory, str)
        manifest = SnapshotStore(
            snapshots,
            RawStore(Path(directory)),
            readers=SourceAdapters(),
            manifest_type=BookDatasetManifest,
        ).read(
            identity,
            max_bytes=config.max_bytes,
        )
        assert manifest.scope == "exploratory_degraded"
        assert result["canonical_parity"] is True
        assert (Path(directory) / "book-prefix.json").is_file()

    @pytest.mark.integration
    def test_installed_restart_and_duplicate_consumer(self, tmp_path: Path) -> None:
        """Recover two sessions, preserve duplicates and resume accepted state outside checkout."""
        snapshots = tmp_path / "snapshots"
        snapshots.mkdir()
        config = replace(TestCapture.config(), retries=1, max_messages=12)
        frames = (*_FRAMES, _FRAMES[-1])
        result = asyncio.run(
            collect(
                config,
                tmp_path / "captures",
                implementation_identity="a" * 64,
                transport=ScriptedTransport(config, (frames, frames)),
                snapshot_directory=snapshots,
                snapshot_records=32,
            )
        )
        assert result["canonical_parity"] is True
        assert result["epochs"] == 2 and result["duplicates"] == 2 and result["updates"] == 2
        directory = result["capture_directory"]
        assert isinstance(directory, str)
        script = tmp_path / "parity_consumer.py"
        shutil.copyfile(_ROOT / "tests/integration/consumers/capture/parity_consumer.py", script)
        process = subprocess.run(
            [sys.executable, "-I", str(script), str(tmp_path / "consumer"), directory],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert process.returncode == 0, (process.stdout, process.stderr)
